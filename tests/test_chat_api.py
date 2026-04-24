"""Tests for FastAPI endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_chat_service
from app.domain.models import RunContext
from app.main import app
from tests.helpers import StaticModelClient, build_chat_service

__all__ = []


def _context(session_id: str, agent_id: str = "agent_main") -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id=agent_id,
        turn_id=f"turn_{session_id}",
        entry_agent_id=agent_id,
        parent_run_id=None,
        trace_flags={},
    )



def test_chat_and_query_endpoints(tmp_path: Path) -> None:
    service, memory_manager = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    memory_manager.write_memory(
        content="Use JSONL storage",
        tags=["storage"],
        context=_context("sess_seed"),
        source_event_id=None,
    )

    app.dependency_overrides[get_chat_service] = lambda: service

    with TestClient(app) as client:
        skills_resp = client.get("/api/skills")
        assert skills_resp.status_code == 200
        assert any(item["name"] == "base" for item in skills_resp.json())

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

        upload_resp = client.post(
            f"/api/sessions/{session_id}/files/upload",
            json={
                "filename": "notes.txt",
                "content_base64": "YWxwaGEgYmV0YQ==",
                "auto_activate": True,
            },
        )
        assert upload_resp.status_code == 200
        file_id = upload_resp.json()["file_id"]
        assert upload_resp.json()["status"] in {"uploaded", "ready", "failed"}

        files_resp = client.get(f"/api/sessions/{session_id}/files")
        assert files_resp.status_code == 200
        assert any(item["file_id"] == file_id for item in files_resp.json()["files"])

        active_resp = client.post(
            f"/api/sessions/{session_id}/active-files",
            json={"file_ids": [file_id]},
        )
        assert active_resp.status_code == 200
        assert file_id in active_resp.json()["active_file_ids"]

    app.dependency_overrides.clear()


def test_chat_stream_endpoint(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="stream-ok"))
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/chat/stream",
                json={
                    "session_id": None,
                    "message": "hello stream",
                    "skill_names": ["base", "memory", "tools"],
                    "max_tool_rounds": 3,
                },
            )
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")

            events = _parse_sse_events(response.text)
            event_names = [name for name, _ in events]
            assert "session" in event_names
            assert "answer_delta" in event_names
            assert "done" in event_names

            done_payload = next(payload for name, payload in events if name == "done")
            assert done_payload["answer"] == "stream-ok"
    finally:
        app.dependency_overrides.clear()


def test_delete_session_endpoint(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="delete-ok"))
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            chat_resp = client.post(
                "/api/chat",
                json={
                    "session_id": None,
                    "message": "create then delete",
                    "skill_names": ["base"],
                    "max_tool_rounds": 1,
                },
            )
            assert chat_resp.status_code == 200
            session_id = chat_resp.json()["session_id"]

            delete_resp = client.delete(f"/api/sessions/{session_id}")
            assert delete_resp.status_code == 200
            assert delete_resp.json()["deleted"] is True

            events_resp = client.get(f"/api/sessions/{session_id}/events")
            assert events_resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_update_session_endpoint(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="rename-ok"))
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            chat_resp = client.post(
                "/api/chat",
                json={
                    "session_id": None,
                    "message": "create for rename",
                    "skill_names": ["base"],
                    "max_tool_rounds": 1,
                },
            )
            assert chat_resp.status_code == 200
            session_id = chat_resp.json()["session_id"]

            patch_resp = client.patch(
                f"/api/sessions/{session_id}",
                json={"title": "项目周报", "is_pinned": True},
            )
            assert patch_resp.status_code == 200
            assert patch_resp.json()["title"] == "项目周报"
            assert patch_resp.json()["is_pinned"] is True

            sessions_resp = client.get("/api/sessions")
            assert sessions_resp.status_code == 200
            target = next(item for item in sessions_resp.json() if item["session_id"] == session_id)
            assert target["title"] == "项目周报"
            assert target["is_pinned"] is True
    finally:
        app.dependency_overrides.clear()


def _parse_sse_events(raw: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())

        payload_text = "\n".join(data_lines)
        payload = json.loads(payload_text) if payload_text else {}
        if isinstance(payload, dict):
            events.append((event_name, payload))
    return events
