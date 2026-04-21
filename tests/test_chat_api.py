"""Tests for FastAPI endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_chat_service
from app.main import app
from tests.helpers import StaticModelClient, build_chat_service

__all__ = []



def test_chat_and_query_endpoints(tmp_path: Path) -> None:
    service, memory_manager = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    memory_manager.write_memory(
        content="Use JSONL storage",
        tags=["storage"],
        session_id="sess_seed",
        source_event_id=None,
    )

    app.dependency_overrides[get_chat_service] = lambda: service

    with TestClient(app) as client:
        chat_resp = client.post(
            "/api/chat",
            json={
                "session_id": None,
                "message": "hello",
                "skill_names": ["base", "memory", "tools"],
                "max_tool_rounds": 3,
            },
        )
        assert chat_resp.status_code == 200
        session_id = chat_resp.json()["session_id"]

        events_resp = client.get(f"/api/sessions/{session_id}/events")
        assert events_resp.status_code == 200
        assert len(events_resp.json()) >= 2

        memories_resp = client.get("/api/memories", params={"limit": 20})
        assert memories_resp.status_code == 200
        assert len(memories_resp.json()) >= 1

    app.dependency_overrides.clear()
