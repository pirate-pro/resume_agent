"""Uvicorn app entrypoint with deterministic write failures for live smoke."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

from app.domain.models import ToolExecutionResult
from app.domain.protocols import ModelResponse, StreamChunk
from app.runtime.agent.tool_gateway import ToolGatewayResult
from app.api.dependencies import services as service_dependencies


class _DeterministicModel:
    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = (system_prompt, messages, tools)
        return ModelResponse(
            content=json.dumps(
                {
                    "note_draft": {
                        "title": "写入恢复 Smoke 面试复盘",
                        "body_markdown": "# 写入恢复 Smoke 面试复盘\n\n验证失败中断和重启恢复。",
                        "summary": "验证 LangGraph 写入恢复。",
                        "tags": ["langgraph", "smoke"],
                    },
                    "application_update_preview": {
                        "stage": "interviewing",
                        "summary": "面试复盘写入恢复验证。",
                        "next_actions": ["验证恢复后项目更新成功。"],
                        "risks": ["项目更新可能发生暂时失败。"],
                        "notes": "由进程级 smoke 生成。",
                    },
                },
                ensure_ascii=False,
            ),
            tool_calls=[],
            model="deterministic-smoke-model",
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt, messages, tools)
        yield StreamChunk(delta=response.content, finished=True, model=response.model)


class _FaultInjectingGateway:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self._tool_name = os.getenv("LANGGRAPH_SMOKE_FAIL_WRITE_TOOL", "").strip()
        self._remaining_path = Path(
            os.getenv("LANGGRAPH_SMOKE_FAILURE_STATE_PATH", "data/langgraph/smoke_write_failures.json")
        )
        self._initial_failures = int(os.getenv("LANGGRAPH_SMOKE_FAIL_WRITE_ATTEMPTS", "0"))

    async def execute_async(self, tool_call: Any, context: Any, **kwargs: Any) -> ToolGatewayResult:
        if tool_call.name == self._tool_name and self._consume_failure():
            return ToolGatewayResult(
                tool_call=tool_call,
                result=ToolExecutionResult(
                    tool_name=tool_call.name,
                    success=False,
                    content=f"smoke injected failure for {tool_call.name}",
                ),
            )
        return cast(ToolGatewayResult, await self._delegate.execute_async(tool_call, context, **kwargs))

    def _consume_failure(self) -> bool:
        self._remaining_path.parent.mkdir(parents=True, exist_ok=True)
        remaining = self._initial_failures
        if self._remaining_path.exists():
            payload = json.loads(self._remaining_path.read_text(encoding="utf-8"))
            remaining = int(payload.get("remaining", 0)) if isinstance(payload, dict) else 0
        if remaining <= 0:
            return False
        self._remaining_path.write_text(
            json.dumps({"remaining": remaining - 1}),
            encoding="utf-8",
        )
        return True


_original_gateway_builder = service_dependencies._build_workflow_tool_gateway


def _build_fault_injecting_gateway() -> Any:
    return _FaultInjectingGateway(_original_gateway_builder())


service_dependencies._build_workflow_tool_gateway = _build_fault_injecting_gateway
setattr(service_dependencies, "get_model_client", lambda: _DeterministicModel())

from app.main import app  # noqa: E402

__all__ = ["app"]
