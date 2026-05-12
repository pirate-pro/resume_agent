"""M11-3 mainline retrieval flow tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.models import AgentRunInput, ToolCall
from app.domain.protocols import ModelResponse, StreamChunk
from tests.test_retrieval_agent_flow import (
    RetrievalFlowBundle,
    _assistant_called,
    _build_retrieval_flow_bundle,
    _context,
    _latest_context_pack,
    _latest_search_hit_id,
    _tool_call_names,
    _tool_names,
)

__all__ = []


@dataclass(frozen=True, slots=True)
class StoreSnapshot:
    career_applications: int
    job_fit_reports: int
    notes: int
    external_resources: int
    interview_questions: int
    learning_tasks: int
    session_artifacts: int


class PrepareInterviewFromHistoryModel:
    """Drive the M11-3 no-id interview-prep path through retrieval only."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        assert "Retrieval 工具只读，不会也不应该触发 memory 写入" in system_prompt
        tool_names = _tool_names(tools)
        assert {"retrieval_search", "retrieval_context_pack", "memory_write"} <= tool_names
        assert not any(name.endswith("_create") or name.endswith("_merge") for name in tool_names)

        if not _assistant_called(messages, "retrieval_search"):
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="retrieval_search",
                        arguments={
                            "query": "之前投过的星河智能 AI Agent 后端岗位",
                            "source_types": ["career_application"],
                            "top_k": 3,
                        },
                    )
                ],
            )

        if not _assistant_called(messages, "retrieval_context_pack"):
            application_id = _latest_search_hit_id(messages, source_type="career_application")
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="retrieval_context_pack",
                        arguments={
                            "query": "星河智能 AI Agent 后端 二面 RAG Agent Runtime 学习任务 面经 面试题",
                            "related_application_id": application_id,
                            "source_types": [
                                "career_application",
                                "job_fit_report",
                                "note",
                                "learning_task",
                                "weakness_tracker",
                                "external_resource",
                                "interview_question",
                            ],
                            "top_k": 12,
                            "max_chars": 8000,
                        },
                    )
                ],
            )

        context_pack = _latest_context_pack(messages)
        source_types = _source_types(context_pack)
        assert {
            "career_application",
            "job_fit_report",
            "note",
            "learning_task",
            "weakness_tracker",
            "external_resource",
            "interview_question",
        } <= source_types
        assert context_pack["citations"]
        assert context_pack["grouped_context"]["career"]
        assert context_pack["grouped_context"]["notes"]
        assert context_pack["grouped_context"]["knowledge"]
        assert context_pack["grouped_context"]["learning"]

        return ModelResponse(
            content=(
                "二面准备建议：先复盘 RAG 检索评估和 chunk 策略，再用 Agent Runtime 架构说明多 Agent 编排。"
                "依据来自已保存的求职项目、匹配报告、RAG 复盘笔记、学习任务、能力短板、面经资料和面试题。"
                "当前不需要新建记录；如果要沉淀新的答案草稿，再保存为笔记。"
            ),
            tool_calls=[],
        )

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        _ = (system_prompt, messages, tools)
        if False:
            yield StreamChunk()
        raise NotImplementedError("streaming is not used in this test")


def test_m11_mainline_recalls_history_and_answers_without_writes(tmp_path: Path) -> None:
    bundle = _build_retrieval_flow_bundle(tmp_path, PrepareInterviewFromHistoryModel())
    before = _snapshot(bundle)

    output = bundle.runtime.run(
        AgentRunInput(
            session_id="sess_alpha",
            user_message="根据我之前星河智能岗位准备二面，不用我提供任何 ID，也先别新建记录。",
            skill_names=["base", "tools", "memory"],
            max_tool_rounds=2,
            context=_context("sess_alpha"),
        )
    )
    events = bundle.stores.sessions.list_events("sess_alpha")

    assert "二面准备建议" in output.answer
    assert "RAG 检索评估" in output.answer
    assert "面经资料和面试题" in output.answer
    assert _snapshot(bundle) == before
    assert _tool_call_names(events) == ["retrieval_search", "retrieval_context_pack"]
    assert "memory_write" not in _tool_call_names(events)
    assert bundle.memory_manager.search(query="星河智能", limit=5, context=_context("sess_alpha")) == []

    tool_results = _tool_result_payloads(events)
    context_payload = next(item for item in tool_results if "context_pack" in item)
    context_pack = context_payload["context_pack"]
    assert _source_types(context_pack) >= {
        "career_application",
        "job_fit_report",
        "note",
        "learning_task",
        "weakness_tracker",
        "external_resource",
        "interview_question",
    }
    assert all(citation["source_id"] for citation in context_pack["citations"])


def _snapshot(bundle: RetrievalFlowBundle) -> StoreSnapshot:
    return StoreSnapshot(
        career_applications=len(bundle.stores.career.list_career_applications(include_archived=True)),
        job_fit_reports=len(bundle.stores.career.list_job_fit_reports(include_archived=True)),
        notes=len(bundle.stores.notes.list_notes(include_archived=True)),
        external_resources=len(bundle.stores.knowledge.list_external_resources(include_archived=True)),
        interview_questions=len(bundle.stores.knowledge.list_interview_questions(include_archived=True)),
        learning_tasks=len(bundle.stores.learning.list_learning_tasks(include_archived=True)),
        session_artifacts=len(bundle.stores.sessions.list_session_artifacts("sess_alpha")),
    )


def _source_types(context_pack: dict[str, Any]) -> set[str]:
    output: set[str] = set()
    hits = context_pack.get("hits")
    if not isinstance(hits, list):
        return output
    for hit in hits:
        if not isinstance(hit, dict) or not isinstance(hit.get("source"), dict):
            continue
        source_type = hit["source"].get("source_type")
        if isinstance(source_type, str):
            output.add(source_type)
    return output


def _tool_result_payloads(events: list[Any]) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for event in events:
        if event.type != "tool_result":
            continue
        content = event.payload.get("content")
        if not isinstance(content, str):
            continue
        decoded = json.loads(content)
        if isinstance(decoded, dict):
            payloads.append(decoded)
    return payloads
