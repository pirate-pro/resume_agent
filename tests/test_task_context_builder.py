"""Tests for deterministic child task context snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from app.career.models import CareerProfile, CareerRecordStatus, ResumeProfile
from app.career.store import CareerProductStore
from app.domain.models import RunContext, SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.services.task_context_builder import TaskContextBuilder


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id="run_main",
        agent_id="agent_main",
        turn_id="turn_main",
        entry_agent_id="agent_main",
    )


def _add_artifact(repository: JsonlSessionRepository, session_id: str, artifact_id: str, text: str) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "original.txt").write_text(text, encoding="utf-8")
    (artifact_dir / "content.txt").write_text(text, encoding="utf-8")
    now = datetime.now(UTC)
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title="jd.txt",
            media_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=f"artifacts/{artifact_id}/original.txt",
            text_relpath=f"artifacts/{artifact_id}/content.txt",
            text_char_count=len(text),
            token_estimate=8,
            parsed_at=now,
        )
    )


def test_task_context_builder_supplies_job_agent_records_and_artifact(tmp_path) -> None:
    session_id = "sess_task_context"
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    session_repository.create_session(session_id)
    _add_artifact(session_repository, session_id, "artifact_jd_ctx_001", "Backend engineer JD: Python APIs.")

    now = datetime.now(UTC)
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    career_store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_ctx_001",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume_ctx_001",
            evidence_refs=["artifact_resume_ctx_001"],
            created_at=now,
            updated_at=now,
            basic_info={"name": "Test User"},
            skills=["Python", "API"],
        )
    )
    career_store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=[session_id],
            created_at=now,
            updated_at=now,
            target_roles=["Backend Engineer"],
            skills=["Python"],
        )
    )

    context = TaskContextBuilder(
        session_repository=session_repository,
        career_store=career_store,
    ).build(
        source_context=_context(session_id),
        target_agent_id="job_agent",
        task_id="task_ctx_001",
        instruction="请基于 resume_profile_ctx_001 评估这个岗位。",
        artifact_refs=["artifact_jd_ctx_001"],
    )

    assert context["phase"] == "jd_fit"
    assert context["known_refs"]["jd_source_artifact_id"] == "artifact_jd_ctx_001"
    assert context["known_refs"]["resume_profile_id"] == "resume_profile_ctx_001"
    assert context["known_refs"]["career_profile_id"] == "career_profile_default"
    assert context["provided_inputs_complete"] is True
    assert context["provided_artifacts"][0]["text_preview"] == "Backend engineer JD: Python APIs."
    assert context["provided_records"]["resume_profile"]["record_id"] == "resume_profile_ctx_001"
    assert context["provided_records"]["career_profile"]["record_id"] == "career_profile_default"
    assert "career_resume_profile_get:resume_profile_ctx_001" in context["reuse_policy"]["already_provided"]


def test_task_context_builder_ignores_schema_field_names_as_refs(tmp_path) -> None:
    session_id = "sess_task_context_schema_refs"
    session_repository = JsonlSessionRepository(data_dir=tmp_path / "sessions")
    session_repository.create_session(session_id)
    _add_artifact(session_repository, session_id, "artifact_jd_ctx_002", "JD: Python.")
    career_store = CareerProductStore(root_dir=tmp_path / "career")

    context = TaskContextBuilder(
        session_repository=session_repository,
        career_store=career_store,
    ).build(
        source_context=_context(session_id),
        target_agent_id="job_agent",
        task_id="task_ctx_002",
        instruction="必须返回 resume_profile_id、career_profile_id、jd_analysis_id 和 job_fit_report_id。",
        artifact_refs=["artifact_jd_ctx_002"],
    )

    assert context["known_refs"]["jd_source_artifact_id"] == "artifact_jd_ctx_002"
    assert "resume_profile_id" not in context["known_refs"]
    assert "jd_analysis_id" not in context["known_refs"]
