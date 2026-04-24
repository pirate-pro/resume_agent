"""Tests for FastAPI endpoints."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.deps import get_chat_service
from app.domain.models import RunContext, ToolCall
from app.domain.protocols import ModelResponse
from app.main import app
from tests.helpers import SequenceModelClient, StaticModelClient, build_chat_service

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
        assert chat_resp.json()["answer_format"] == "plain_text"
        assert chat_resp.json()["render_hint"] == "plain"

        events_resp = client.get(f"/api/sessions/{session_id}/events")
        assert events_resp.status_code == 200
        assert len(events_resp.json()) >= 2

        messages_resp = client.get(f"/api/sessions/{session_id}/messages")
        assert messages_resp.status_code == 200
        assistant_message = next(item for item in messages_resp.json() if item["role"] == "assistant")
        assert assistant_message["answer_format"] == "plain_text"
        assert assistant_message["render_hint"] == "plain"

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
    service, _ = build_chat_service(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="```markdown\n# 流式标题\n\n内容\n```"),
    )
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
            assert "answer_meta" in event_names
            assert "answer_delta" in event_names
            assert "done" in event_names

            answer_meta = next(payload for name, payload in events if name == "answer_meta")
            assert answer_meta["answer_format"] == "markdown"
            assert answer_meta["render_hint"] == "markdown_document"

            done_payload = next(payload for name, payload in events if name == "done")
            assert done_payload["answer"] == "# 流式标题\n\n内容"
            assert done_payload["answer_format"] == "markdown"
            assert done_payload["render_hint"] == "markdown_document"
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_answer_meta_contains_artifacts_after_tool_round(tmp_path: Path) -> None:
    service, _ = build_chat_service(
        data_dir=tmp_path,
        model_client=SequenceModelClient(
            responses=[
                ModelResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            name="workspace_write_file",
                            arguments={"path": "report.md", "content": "# 周报\n\n内容"},
                        )
                    ],
                ),
                ModelResponse(content="# 周报\n\n内容", tool_calls=[]),
            ]
        ),
    )
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/chat/stream",
                json={
                    "session_id": "sess_stream_artifacts",
                    "message": "生成一份 markdown 周报并展示给我",
                    "skill_names": ["base", "tools"],
                    "max_tool_rounds": 2,
                },
            )
            assert response.status_code == 200

            events = _parse_sse_events(response.text)
            answer_meta = next(payload for name, payload in events if name == "answer_meta")
            assert answer_meta["render_hint"] == "markdown_document"
            assert answer_meta["source_kind"] == "generated_document"
            assert answer_meta["artifacts"] == [
                {
                    "type": "file",
                    "path": "report.md",
                    "role": "generated",
                }
            ]
    finally:
        app.dependency_overrides.clear()


def test_workspace_file_preview_endpoint(tmp_path: Path) -> None:
    service, _ = build_chat_service(data_dir=tmp_path, model_client=StaticModelClient(content="preview-ok"))
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            chat_resp = client.post(
                "/api/chat",
                json={
                    "session_id": "sess_workspace_preview_api",
                    "message": "create preview session",
                    "skill_names": ["base"],
                    "max_tool_rounds": 1,
                },
            )
            assert chat_resp.status_code == 200

            workspace = service._session_repository.get_workspace_path("sess_workspace_preview_api")  # noqa: SLF001
            (workspace / "draft.md").write_text(
                "# 预览文档\n\n```python\nprint('hi')\n```\n",
                encoding="utf-8",
            )

            preview_resp = client.get(
                "/api/sessions/sess_workspace_preview_api/workspace-files/preview",
                params={"path": "draft.md", "max_chars": 12000},
            )
            assert preview_resp.status_code == 200
            payload = preview_resp.json()
            assert payload["path"] == "draft.md"
            assert payload["answer_format"] == "markdown"
            assert payload["render_hint"] == "markdown_document"
            assert payload["content"].startswith("# 预览文档")
    finally:
        app.dependency_overrides.clear()


def test_session_messages_endpoint_returns_render_protocol(tmp_path: Path) -> None:
    service, _ = build_chat_service(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="```markdown\n# 标题\n\n正文\n```"),
    )
    app.dependency_overrides[get_chat_service] = lambda: service

    try:
        with TestClient(app) as client:
            chat_resp = client.post(
                "/api/chat",
                json={
                    "session_id": "sess_render_protocol",
                    "message": "给我一个 markdown 示例",
                    "skill_names": ["base"],
                    "max_tool_rounds": 1,
                },
            )
            assert chat_resp.status_code == 200
            assert chat_resp.json()["answer"] == "# 标题\n\n正文"
            assert chat_resp.json()["answer_format"] == "markdown"
            assert chat_resp.json()["render_hint"] == "markdown_document"

            messages_resp = client.get("/api/sessions/sess_render_protocol/messages")
            assert messages_resp.status_code == 200
            assistant_message = next(item for item in messages_resp.json() if item["role"] == "assistant")
            assert assistant_message["content"] == "# 标题\n\n正文"
            assert assistant_message["answer_format"] == "markdown"
            assert assistant_message["render_hint"] == "markdown_document"
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
