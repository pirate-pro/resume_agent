"""Tests for FastAPI endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import (
    get_chat_service,
    get_memory_query_service,
    get_session_artifact_service,
    get_session_query_service,
)
from app.domain.models import RunContext, ToolCall
from app.domain.protocols import ModelResponse
from app.main import app
from tests.helpers import ChatServiceBundle, SequenceModelClient, StaticModelClient, build_chat_service_bundle

__all__ = []


def test_health_endpoint_exposes_mid_term_queue_summary() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = _data(response)
    assert payload["status"] in {"ok", "degraded"}
    assert "mid_term_flush" in payload
    mid_term = payload["mid_term_flush"]
    assert isinstance(mid_term.get("worker_enabled"), bool)
    if "queue" in mid_term:
        queue = mid_term["queue"]
        assert queue["targets"] >= 0
        assert queue["total"] >= 0
        assert queue["due"] >= 0
        assert queue["retry"] >= 0
        assert queue["deferred"] >= 0
        assert queue["succeeded"] >= 0
    else:
        assert isinstance(mid_term.get("error"), str)


def test_request_validation_error_uses_standard_response() -> None:
    with TestClient(app) as client:
        response = client.post("/api/chat", json={"message": ""})

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == 422
    assert payload["msg"] == "request validation failed"
    assert payload["data"] is None


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
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    service = bundle.chat_service
    memory_manager = bundle.memory_manager
    memory_manager.write_memory(
        content="Use JSONL storage",
        tags=["storage"],
        context=_context("sess_seed"),
        source_event_id=None,
    )

    _override_api_services(bundle)

    with TestClient(app) as client:
        skills_resp = client.get("/api/skills")
        assert skills_resp.status_code == 200
        assert any(item["name"] == "base" for item in _data(skills_resp))

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
        chat_payload = _data(chat_resp)
        session_id = chat_payload["session_id"]
        assert chat_payload["answer_format"] == "plain_text"
        assert chat_payload["render_hint"] == "plain"
        assert chat_payload["layout_hint"] == "brief"

        events_resp = client.get(f"/api/sessions/{session_id}/events")
        assert events_resp.status_code == 200
        assert len(_data(events_resp)) >= 2

        messages_resp = client.get(f"/api/sessions/{session_id}/messages")
        assert messages_resp.status_code == 200
        assistant_message = next(item for item in _data(messages_resp) if item["role"] == "assistant")
        assert assistant_message["answer_format"] == "plain_text"
        assert assistant_message["render_hint"] == "plain"
        assert assistant_message["layout_hint"] == "brief"

        memories_resp = client.get("/api/memories", params={"limit": 20})
        assert memories_resp.status_code == 200
        assert len(_data(memories_resp)) >= 1

        upload_resp = client.post(
            f"/api/sessions/{session_id}/artifacts/upload",
            json={
                "filename": "notes.txt",
                "content_base64": "YWxwaGEgYmV0YQ==",
                "auto_activate": True,
            },
        )
        assert upload_resp.status_code == 200
        upload_payload = _data(upload_resp)
        artifact_id = upload_payload["artifact_id"]
        assert upload_payload["status"] in {"uploaded", "ready", "failed"}

        artifacts_resp = client.get(f"/api/sessions/{session_id}/artifacts")
        assert artifacts_resp.status_code == 200
        artifacts_payload = _data(artifacts_resp)
        assert any(item["artifact_id"] == artifact_id for item in artifacts_payload["artifacts"])

        active_resp = client.post(
            f"/api/sessions/{session_id}/active-artifacts",
            json={"artifact_ids": [artifact_id]},
        )
        assert active_resp.status_code == 200
        assert artifact_id in _data(active_resp)["active_artifact_ids"]

    app.dependency_overrides.clear()


def test_chat_stream_endpoint(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="```markdown\n# 流式标题\n\n内容\n```"),
    )
    _override_api_services(bundle)

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
            assert answer_meta["layout_hint"] == "paragraph"

            done_payload = next(payload for name, payload in events if name == "done")
            assert done_payload["answer"] == "# 流式标题\n\n内容"
            assert done_payload["answer_format"] == "markdown"
            assert done_payload["render_hint"] == "markdown_document"
            assert done_payload["layout_hint"] == "paragraph"
    finally:
        app.dependency_overrides.clear()


def test_chat_stream_answer_meta_contains_artifacts_after_tool_round(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(
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
    _override_api_services(bundle)

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
            assert answer_meta["layout_hint"] == "paragraph"
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
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="preview-ok"))
    service = bundle.chat_service
    _override_api_services(bundle)

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
            payload = _data(preview_resp)
            assert payload["path"] == "draft.md"
            assert payload["answer_format"] == "markdown"
            assert payload["render_hint"] == "markdown_document"
            assert payload["layout_hint"] == "paragraph"
            assert payload["content"].startswith("# 预览文档")
    finally:
        app.dependency_overrides.clear()


def test_session_messages_endpoint_returns_render_protocol(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(
        data_dir=tmp_path,
        model_client=StaticModelClient(content="```markdown\n# 标题\n\n正文\n```"),
    )
    _override_api_services(bundle)

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
            chat_payload = _data(chat_resp)
            assert chat_payload["answer"] == "# 标题\n\n正文"
            assert chat_payload["answer_format"] == "markdown"
            assert chat_payload["render_hint"] == "markdown_document"
            assert chat_payload["layout_hint"] == "paragraph"

            messages_resp = client.get("/api/sessions/sess_render_protocol/messages")
            assert messages_resp.status_code == 200
            assistant_message = next(item for item in _data(messages_resp) if item["role"] == "assistant")
            assert assistant_message["content"] == "# 标题\n\n正文"
            assert assistant_message["answer_format"] == "markdown"
            assert assistant_message["render_hint"] == "markdown_document"
            assert assistant_message["layout_hint"] == "paragraph"
    finally:
        app.dependency_overrides.clear()


def test_delete_session_endpoint(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="delete-ok"))
    _override_api_services(bundle)

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
            session_id = _data(chat_resp)["session_id"]

            delete_resp = client.delete(f"/api/sessions/{session_id}")
            assert delete_resp.status_code == 200
            assert _data(delete_resp)["deleted"] is True

            events_resp = client.get(f"/api/sessions/{session_id}/events")
            assert events_resp.status_code == 404
            assert events_resp.json()["code"] == 404
    finally:
        app.dependency_overrides.clear()


def test_update_session_endpoint(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="rename-ok"))
    _override_api_services(bundle)

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
            session_id = _data(chat_resp)["session_id"]

            patch_resp = client.patch(
                f"/api/sessions/{session_id}",
                json={"title": "项目周报", "is_pinned": True},
            )
            assert patch_resp.status_code == 200
            patch_payload = _data(patch_resp)
            assert patch_payload["title"] == "项目周报"
            assert patch_payload["is_pinned"] is True

            sessions_resp = client.get("/api/sessions")
            assert sessions_resp.status_code == 200
            target = next(item for item in _data(sessions_resp) if item["session_id"] == session_id)
            assert target["title"] == "项目周报"
            assert target["is_pinned"] is True
    finally:
        app.dependency_overrides.clear()


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _override_api_services(bundle: ChatServiceBundle) -> None:
    app.dependency_overrides[get_chat_service] = lambda: bundle.chat_service
    app.dependency_overrides[get_session_query_service] = lambda: bundle.session_query_service
    app.dependency_overrides[get_session_artifact_service] = lambda: bundle.session_artifact_service
    app.dependency_overrides[get_memory_query_service] = lambda: bundle.memory_query_service


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
