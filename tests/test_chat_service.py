"""Tests for chat service orchestration."""

from __future__ import annotations

import asyncio
from pathlib import Path

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
