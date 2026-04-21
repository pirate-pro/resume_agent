"""Tests for FastAPI endpoints."""

from __future__ import annotations

import json
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
