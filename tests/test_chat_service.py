"""Tests for chat service orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.domain.models import AgentRunOutput
from app.schemas.chat import ChatRequest
from tests.helpers import StaticModelClient, build_chat_service

__all__ = []



def test_chat_service_creates_session_when_missing(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="hi"))

    response = asyncio.run(
        service.chat(
            ChatRequest(
                session_id=None,
                message="hello",
                skill_names=["base"],
                max_tool_rounds=3,
            )
        )
    )

    assert response.session_id.startswith("sess_")
    assert response.answer == "hi"



def test_chat_service_returns_runtime_response(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="result"))

    response = asyncio.run(
        service.chat(
            ChatRequest(
                session_id="sess_explicit",
                message="go",
                skill_names=["base", "memory"],
                max_tool_rounds=2,
            )
        )
    )

    assert response.session_id == "sess_explicit"
    assert response.answer == "result"


def test_chat_service_delete_session(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="result"))
    created = asyncio.run(
        service.chat(
            ChatRequest(
                session_id=None,
                message="to be deleted",
                skill_names=["base"],
                max_tool_rounds=1,
            )
        )
    )

    asyncio.run(service.delete_session(created.session_id))

    assert service._session_repository.get_session(created.session_id) is None  # noqa: SLF001


def test_chat_stream_emits_heartbeat_when_idle(tmp_path: Path) -> None:
    service, _ = build_chat_service(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="idle"),
        stream_heartbeat_interval_seconds=0.01,
        stream_run_timeout_seconds=1.0,
    )

    async def _slow_run_stream(run_input, channel):  # noqa: ANN001, ANN202
        _ = channel
        await asyncio.sleep(0.04)
        return AgentRunOutput(
            session_id=run_input.session_id,
            answer="idle done",
            tool_calls=[],
            memory_hits=[],
        )

    service._runtime.run_stream = _slow_run_stream  # noqa: SLF001

    async def _collect_events() -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        async for item in service.chat_stream(
            ChatRequest(
                session_id=None,
                message="heartbeat",
                skill_names=["base"],
                max_tool_rounds=1,
            )
        ):
            output.append(item)
        return output

    events = asyncio.run(_collect_events())
    event_names = [str(item.get("event", "")) for item in events]
    assert "session" in event_names
    assert "heartbeat" in event_names
    assert "done" in event_names


def test_chat_stream_times_out_and_emits_error(tmp_path: Path) -> None:
    service, _ = build_chat_service(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="timeout"),
        stream_heartbeat_interval_seconds=0.01,
        stream_run_timeout_seconds=0.03,
    )

    async def _never_finishes(run_input, channel):  # noqa: ANN001, ANN202
        _ = (run_input, channel)
        await asyncio.sleep(0.2)
        return AgentRunOutput(
            session_id="sess_timeout",
            answer="unreachable",
            tool_calls=[],
            memory_hits=[],
        )

    service._runtime.run_stream = _never_finishes  # noqa: SLF001

    async def _collect_events() -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        async for item in service.chat_stream(
            ChatRequest(
                session_id=None,
                message="timeout",
                skill_names=["base"],
                max_tool_rounds=1,
            )
        ):
            output.append(item)
        return output

    events = asyncio.run(_collect_events())
    event_names = [str(item.get("event", "")) for item in events]
    assert "error" in event_names
    error_payload = next(item.get("data", {}) for item in events if item.get("event") == "error")
    assert "timed out" in str(error_payload)
