"""Tests for child-agent output reference extraction."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.domain.models import EventRecord
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.services.agent_result_refs import collect_agent_output_refs

__all__ = []


def test_collect_agent_output_refs_ignores_schema_field_names(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_refs")
    repository.append_event(
        "sess_refs",
        EventRecord(
            event_id="evt_tool_result",
            session_id="sess_refs",
            type="tool_result",
            payload={
                "tool_name": "career_job_fit_report_save",
                "success": True,
                "content": json.dumps(
                    {
                        "record_type": "job_fit_report",
                        "record": {
                            "job_fit_report_id": "fit_alpha_001",
                            "jd_analysis_id": "jd_alpha_001",
                            "report_artifact_id": "artifact_report_001",
                            "source_artifact_id": "artifact_input_001",
                        },
                        "message": "字段名 artifact_id / resume_profile_id / jd_analysis_id 不应被当成引用。",
                    },
                    ensure_ascii=False,
                ),
            },
            created_at=datetime.now(UTC),
            agent_id="job_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )

    refs = collect_agent_output_refs(
        session_repository=repository,
        session_id="sess_refs",
        agent_id="job_agent",
        run_id="run_child",
        input_artifact_refs=["artifact_input_001"],
    )

    assert refs.output_artifact_refs == ["artifact_report_001"]
    assert refs.artifact_refs == ["artifact_report_001", "artifact_input_001"]
    assert refs.product_refs == ["jd_alpha_001", "fit_alpha_001"]


def test_collect_agent_output_refs_ignores_assistant_messages_and_failed_tool_results(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_refs")
    repository.append_event(
        "sess_refs",
        EventRecord(
            event_id="evt_assistant",
            session_id="sess_refs",
            type="assistant_message",
            payload={
                "content": (
                    "career_profile_merge 不存在，已改用 career_profile_default。"
                    " career_profile_get 是读取工具，不是产品记录。"
                    " resume_profile_and_diagnosis_ready_stop_low_level_actions 是运行时原因，不是画像。"
                    " JDAnalysis=jd_alpha_001，JobFitReport=fit_alpha_001。"
                )
            },
            created_at=datetime.now(UTC),
            agent_id="job_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )
    repository.append_event(
        "sess_refs",
        EventRecord(
            event_id="evt_failed_tool_result",
            session_id="sess_refs",
            type="tool_result",
            payload={
                "tool_name": "career_job_fit_report_save",
                "success": False,
                "content": (
                    "CareerProfile not found: career_profile_agent. "
                    "Partial refs: jd_alpha_001, fit_alpha_001, resume_profile_alpha_001."
                ),
            },
            created_at=datetime.now(UTC),
            agent_id="job_agent",
            run_id="run_child",
            parent_run_id="run_main",
        ),
    )

    refs = collect_agent_output_refs(
        session_repository=repository,
        session_id="sess_refs",
        agent_id="job_agent",
        run_id="run_child",
        input_artifact_refs=[],
    )

    assert refs.product_refs == []


def test_collect_agent_output_refs_only_treats_write_tools_as_output_artifacts(tmp_path: Path) -> None:
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session("sess_refs")
    for event_id, tool_name, content in [
        (
            "evt_read",
            "session_read_artifact",
            {"artifact_id": "artifact_source_001", "content": "source text"},
        ),
        (
            "evt_create",
            "session_create_text_artifact",
            {"artifact_id": "artifact_report_001", "title": "诊断报告.md"},
        ),
    ]:
        repository.append_event(
            "sess_refs",
            EventRecord(
                event_id=event_id,
                session_id="sess_refs",
                type="tool_result",
                payload={
                    "tool_name": tool_name,
                    "success": True,
                    "content": json.dumps(content, ensure_ascii=False),
                },
                created_at=datetime.now(UTC),
                agent_id="resume_agent",
                run_id="run_child",
                parent_run_id="run_main",
            ),
        )

    refs = collect_agent_output_refs(
        session_repository=repository,
        session_id="sess_refs",
        agent_id="resume_agent",
        run_id="run_child",
        input_artifact_refs=["artifact_source_001"],
    )

    assert refs.output_artifact_refs == ["artifact_report_001"]
    assert refs.artifact_refs == ["artifact_report_001", "artifact_source_001"]
