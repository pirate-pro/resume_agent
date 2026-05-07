"""Pressure tests for session artifact storage and tool access."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.domain.models import RunContext
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.schemas.chat import ActiveArtifactsRequest
from app.tools.builtin_tools.session_artifacts import (
    SessionListArtifactsTool,
    SessionReadArtifactTool,
    SessionSearchArtifactTool,
)
from tests.helpers import StaticModelClient, build_chat_service_bundle

__all__ = []


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def test_session_artifact_upload_activation_and_tool_access_pressure(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    session_id = "sess_artifact_pressure"
    uploaded_ids: list[str] = []

    for index in range(80):
        body = (
            f"# artifact {index}\n"
            f"marker_{index} 用户资料片段 {index}\n"
            "这是一段用于压测上传、激活、惰性解析、读取和搜索链路的文本。\n"
        ) * 12
        view = asyncio.run(
            bundle.session_artifact_service.upload_session_artifact(
                session_id=session_id,
                filename=f"profile_{index}.txt",
                content_bytes=body.encode("utf-8"),
                auto_activate=index % 4 == 0,
            )
        )
        uploaded_ids.append(view.artifact_id)

    response = bundle.session_artifact_service.list_session_artifacts(session_id)
    session_root = tmp_path / "sessions" / session_id

    assert len(response.artifacts) == 80
    assert len(response.active_artifact_ids) == 20
    assert all(item.artifact_id.startswith("artifact_") for item in response.artifacts)
    assert (session_root / "artifacts.json").exists()
    assert (session_root / "artifacts").is_dir()
    assert not (session_root / "files.json").exists()

    repository = JsonlSessionRepository(data_dir=tmp_path)
    context = _context(session_id)
    list_payload = json.loads(
        SessionListArtifactsTool(repository).execute({}, context).content
    )
    assert len(list_payload["artifacts"]) == 80

    target_artifact_id = uploaded_ids[37]
    read_payload = json.loads(
        SessionReadArtifactTool(repository)
        .execute(
            {"artifact_id": target_artifact_id, "offset": 0, "max_chars": 2000},
            context,
        )
        .content
    )
    assert "marker_37" in read_payload["content"]
    assert read_payload["status"] == "ready"

    search_payload = json.loads(
        SessionSearchArtifactTool(repository)
        .execute(
            {"artifact_id": target_artifact_id, "query": "marker_37", "top_k": 3},
            context,
        )
        .content
    )
    assert search_payload["hit_count"] >= 1
    assert "marker_37" in search_payload["hits"][0]["snippet"]


def test_artifact_activation_ignores_missing_ids_under_pressure(tmp_path: Path) -> None:
    bundle = build_chat_service_bundle(data_dir=tmp_path, model_client=StaticModelClient(content="ok"))
    session_id = "sess_artifact_active_pressure"
    uploaded_ids: list[str] = []

    for index in range(30):
        view = asyncio.run(
            bundle.session_artifact_service.upload_session_artifact(
                session_id=session_id,
                filename=f"doc_{index}.md",
                content_bytes=f"# doc {index}\nmarker active {index}\n".encode("utf-8"),
                auto_activate=False,
            )
        )
        uploaded_ids.append(view.artifact_id)

    response = bundle.session_artifact_service.set_active_artifacts(
        session_id,
        request=ActiveArtifactsRequest(
            artifact_ids=[uploaded_ids[3], "artifact_missing", uploaded_ids[8], uploaded_ids[3]],
        ),
    )

    assert response.active_artifact_ids == [uploaded_ids[3], uploaded_ids[8]]
    assert len(response.artifacts) == 30
