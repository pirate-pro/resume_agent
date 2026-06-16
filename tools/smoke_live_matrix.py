"""Cross-scenario live smoke runner for product workflow regression.

Run:
  uv run python tools/smoke_live_matrix.py --all-p0 --runs 1
  uv run python tools/smoke_live_matrix.py --scenario chat_only --scenario note_write --runs 1
  uv run python tools/smoke_live_matrix.py --scenario career_full --runs 6 --concurrency 3

This script uses the real configured model endpoint. It is intentionally not
part of pytest because model availability, latency, and tool-call behavior are
environment-dependent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
)
from app.core.settings import Settings
from app.core.time import app_now, to_app_iso
from app.domain.models import AgentRunInput, RunContext
from app.notes.models import Note, NoteOrigin, NoteRecordStatus, NoteSourceRef, NoteSourceType, NoteType
from app.runtime.event_channel import EventChannel
from app.schemas.chat import ChatRequest, WorkflowResumeStreamRequest
from tools.smoke_career_live_flow import (
    FlowReport,
    LiveStack,
    TurnReport,
    _compact_json,
    _compact_text,
    _int_value,
    _prepare_clean_run_data_dir,
    _preview_list,
    _runtime_config_text,
    add_jd_artifact,
    add_resume_artifact,
    build_live_stack,
    efficiency_summary,
    hard_safety_limit_detected,
    internal_runtime_answer_detected,
    latest_event_summaries,
    path_argument_leaked,
    retrieval_quality_summary,
    run_live_flow,
    tool_call_counts,
    tool_loop_stagnation_detected,
    unusable_final_answer_detected,
)
from tools.career_live_quality_gate import check_career_live_quality

P0_SCENARIOS = (
    "chat_only",
    "memory_write",
    "note_write",
    "rag_read_only",
    "main_resume_child",
    "main_job_child",
    "career_full",
)
P1_SCENARIOS = (
    "career_custom_resume",
    "rag_to_note",
    "rag_to_learning_task",
    "interview_review",
    "interactive_rag_to_note_source_select",
    "interactive_rag_to_note_user_supplement",
    "interactive_rag_to_note_review_edit",
    "interactive_rag_to_note_retry_retrieval",
    "interactive_interview_review_scope_select",
    "interactive_interview_review_user_supplement",
    "interactive_interview_review_review_edit",
)
ALL_SCENARIOS = P0_SCENARIOS + P1_SCENARIOS
INTERACTIVE_RAG_TO_NOTE_SCENARIOS = {
    "interactive_rag_to_note_source_select",
    "interactive_rag_to_note_user_supplement",
    "interactive_rag_to_note_review_edit",
    "interactive_rag_to_note_retry_retrieval",
}
INTERACTIVE_INTERVIEW_REVIEW_SCENARIOS = {
    "interactive_interview_review_scope_select",
    "interactive_interview_review_user_supplement",
    "interactive_interview_review_review_edit",
}


class _DiscardingEventChannel(EventChannel):
    async def emit(self, event: str, data: dict[str, Any]) -> None:
        _ = (event, data)


_WRITE_TOOLS = {
    "career_application_create",
    "career_application_merge",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
    "career_profile_merge",
    "career_resume_profile_save",
    "career_resume_version_create",
    "learning_checkin_create",
    "learning_plan_create",
    "learning_task_create",
    "learning_task_update_state",
    "learning_weakness_create",
    "learning_weakness_update",
    "memory_forget",
    "memory_update",
    "memory_write",
    "note_append",
    "note_archive",
    "note_collection_archive",
    "note_collection_create",
    "note_collection_update",
    "note_create",
    "note_update",
    "publish_artifact",
    "session_create_text_artifact",
    "state_publish",
    "state_set",
    "workspace_write_file",
}
_BLOCKING_WORKFLOW_DECISIONS = {
    "hard_model_round_limit_reached",
    "premature_final_answer_stagnation",
    "tool_loop_stagnation",
}
_P0_COST_WARNING_LIMITS = {
    "chat_only": {"elapsed_seconds": 30, "total_llm_calls": 3, "total_llm_tokens": 10_000},
    "memory_write": {"elapsed_seconds": 60, "total_llm_calls": 6, "total_llm_tokens": 20_000},
    "note_write": {"elapsed_seconds": 90, "total_llm_calls": 8, "total_llm_tokens": 30_000},
    "rag_read_only": {"elapsed_seconds": 120, "total_llm_calls": 10, "total_llm_tokens": 50_000},
    "main_resume_child": {"elapsed_seconds": 180, "total_llm_calls": 14, "total_llm_tokens": 90_000},
    "main_job_child": {"elapsed_seconds": 220, "total_llm_calls": 16, "total_llm_tokens": 110_000},
    "career_full": {"elapsed_seconds": 360, "total_llm_calls": 30, "total_llm_tokens": 180_000},
}


@dataclass(frozen=True, slots=True)
class ScenarioTurnSpec:
    name: str
    message: str
    skill_names: tuple[str, ...] = ("base", "tools", "memory", "file-reader")


@dataclass(slots=True)
class ScenarioReport:
    scenario: str
    tier: str
    run_index: int
    session_id: str
    data_dir: Path
    success: bool
    elapsed_seconds: float
    turns: list[TurnReport] = field(default_factory=list)
    tool_call_counts: dict[str, int] = field(default_factory=dict)
    write_tool_counts: dict[str, int] = field(default_factory=dict)
    record_counts: dict[str, int] = field(default_factory=dict)
    artifact_count: int = 0
    quality_error_codes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    efficiency: dict[str, Any] = field(default_factory=dict)
    retrieval_quality: dict[str, Any] = field(default_factory=dict)
    workflow_event_counts: dict[str, int] = field(default_factory=dict)
    last_events: list[str] = field(default_factory=list)


def run_matrix_scenario(
    *,
    scenario: str,
    run_index: int,
    root_data_dir: Path,
    settings: Settings,
    max_tool_rounds: int,
    stream: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ScenarioReport:
    scenario = _normalize_scenario(scenario)
    if scenario in INTERACTIVE_RAG_TO_NOTE_SCENARIOS:
        return _run_interactive_rag_to_note_scenario(
            scenario=scenario,
            run_index=run_index,
            root_data_dir=root_data_dir,
            settings=settings,
            max_tool_rounds=max_tool_rounds,
            stream=stream,
            progress=progress,
        )
    if scenario in INTERACTIVE_INTERVIEW_REVIEW_SCENARIOS:
        return _run_interactive_interview_review_scenario(
            scenario=scenario,
            run_index=run_index,
            root_data_dir=root_data_dir,
            settings=settings,
            max_tool_rounds=max_tool_rounds,
            stream=stream,
            progress=progress,
        )
    if scenario in {"career_full", "career_custom_resume", "rag_to_note", "rag_to_learning_task", "interview_review"}:
        return _run_career_backed_scenario(
            scenario=scenario,
            run_index=run_index,
            root_data_dir=root_data_dir,
            settings=settings,
            max_tool_rounds=max_tool_rounds,
            stream=stream,
            progress=progress,
        )

    run_data_dir = _prepare_clean_run_data_dir(root_data_dir / scenario, run_index)
    stack = build_live_stack(data_dir=run_data_dir, settings=settings)
    session_id = f"sess_live_{scenario}_{run_index:03d}_{uuid4().hex[:8]}"
    report = ScenarioReport(
        scenario=scenario,
        tier=_scenario_tier(scenario),
        run_index=run_index,
        session_id=session_id,
        data_dir=run_data_dir,
        success=False,
        elapsed_seconds=0.0,
    )
    started = time.perf_counter()
    try:
        stack.session_repository.create_session(session_id)
        _setup_simple_scenario(stack=stack, scenario=scenario, session_id=session_id, run_index=run_index)
        for turn in _simple_scenario_turns(scenario, run_index=run_index):
            report.turns.append(
                _run_turn(
                    stack=stack,
                    session_id=session_id,
                    turn=turn,
                    max_tool_rounds=max_tool_rounds,
                    run_index=run_index,
                    stream=stream,
                    progress=progress,
                )
            )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc) or exc.__class__.__name__)
        _progress(progress, scenario, run_index, f"异常：{report.errors[-1]}")
    report.elapsed_seconds = time.perf_counter() - started
    inspect_matrix_outputs(stack=stack, report=report)
    _progress(
        progress,
        scenario,
        run_index,
        f"结束：{'通过' if report.success else '失败'}，耗时 {report.elapsed_seconds:.2f}s",
    )
    return report


def inspect_matrix_outputs(*, stack: LiveStack, report: ScenarioReport) -> None:
    report.tool_call_counts = tool_call_counts(stack.session_repository, report.session_id)
    report.write_tool_counts = {name: count for name, count in report.tool_call_counts.items() if name in _WRITE_TOOLS}
    report.record_counts = _record_counts_for_session(stack=stack, session_id=report.session_id)
    report.artifact_count = len(stack.session_repository.list_session_artifacts(report.session_id))
    report.efficiency = efficiency_summary(stack.session_repository, report.session_id)
    report.retrieval_quality = retrieval_quality_summary(stack.session_repository, report.session_id)
    report.workflow_event_counts = _workflow_event_counts(stack=stack, session_id=report.session_id)

    _apply_common_gates(stack=stack, report=report)
    _apply_scenario_gates(report)
    _apply_live_quality_gate(stack=stack, report=report)
    _apply_product_stop_line(report)

    report.success = not report.errors
    if report.errors:
        report.last_events = latest_event_summaries(stack.session_repository, report.session_id)


def _run_career_backed_scenario(
    *,
    scenario: str,
    run_index: int,
    root_data_dir: Path,
    settings: Settings,
    max_tool_rounds: int,
    stream: bool,
    progress: Callable[[str], None] | None,
) -> ScenarioReport:
    project_action = "none"
    retrieval_action = "none"
    if scenario == "career_custom_resume":
        project_action = "custom_resume"
    elif scenario == "rag_to_note":
        retrieval_action = "save_note"
    elif scenario == "rag_to_learning_task":
        retrieval_action = "learning_task"
    elif scenario == "interview_review":
        retrieval_action = "interview_review"

    flow = run_live_flow(
        run_index=run_index,
        root_data_dir=root_data_dir / scenario,
        settings=settings,
        max_tool_rounds=max_tool_rounds,
        project_action=project_action,
        retrieval_action=retrieval_action,
        setup_mode="full" if scenario == "career_full" else "seeded",
        stream=stream,
        progress=lambda message: _progress(progress, scenario, run_index, message),
    )
    return _scenario_report_from_flow(scenario, flow)


def _scenario_report_from_flow(scenario: str, flow: FlowReport) -> ScenarioReport:
    write_counts = {name: count for name, count in flow.tool_call_counts.items() if name in _WRITE_TOOLS}
    errors = list(flow.errors)
    if scenario == "career_full":
        _require_record_counts(
            scenario=scenario,
            record_counts={key: len(value) for key, value in flow.record_ids.items()},
            errors=errors,
            required={
                "resume_profiles": 1,
                "jd_analyses": 1,
                "job_fit_reports": 1,
                "career_applications": 1,
                "resume_versions": 1,
            },
        )
    report = ScenarioReport(
        scenario=scenario,
        tier=_scenario_tier(scenario),
        run_index=flow.run_index,
        session_id=flow.session_id,
        data_dir=flow.data_dir,
        success=False,
        elapsed_seconds=flow.elapsed_seconds,
        turns=list(flow.turns),
        tool_call_counts=dict(flow.tool_call_counts),
        write_tool_counts=write_counts,
        record_counts={key: len(value) for key, value in flow.record_ids.items()},
        artifact_count=len(flow.artifact_ids),
        quality_error_codes=list(flow.quality_error_codes),
        warnings=list(flow.warnings),
        errors=errors,
        efficiency=dict(flow.efficiency),
        retrieval_quality=dict(flow.retrieval_quality),
        last_events=list(flow.last_events),
    )
    _apply_product_stop_line(report)
    report.success = flow.success and not report.errors
    return report


def _run_interactive_rag_to_note_scenario(
    *,
    scenario: str,
    run_index: int,
    root_data_dir: Path,
    settings: Settings,
    max_tool_rounds: int,
    stream: bool,
    progress: Callable[[str], None] | None,
) -> ScenarioReport:
    _ = stream
    langgraph_settings = settings.model_copy(
        update={
            "langgraph_workflow_enabled": True,
            "langgraph_interactive_note_enabled": True,
            "langgraph_workflow_backend": "memory",
        }
    )
    run_data_dir = _prepare_clean_run_data_dir(root_data_dir / scenario, run_index)
    stack = build_live_stack(data_dir=run_data_dir, settings=langgraph_settings)
    if stack.chat_service is None:
        raise RuntimeError("ChatService is required for interactive LangGraph smoke.")
    session_id = f"sess_live_{scenario}_{run_index:03d}_{uuid4().hex[:8]}"
    report = ScenarioReport(
        scenario=scenario,
        tier=_scenario_tier(scenario),
        run_index=run_index,
        session_id=session_id,
        data_dir=run_data_dir,
        success=False,
        elapsed_seconds=0.0,
    )
    started = time.perf_counter()
    try:
        stack.session_repository.create_session(session_id)
        stack.session_repository.update_session_title(session_id, f"M59 {scenario}")
        resume_artifact_id = f"artifact_resume_interactive_{run_index:03d}"
        jd_artifact_id = f"artifact_jd_interactive_{run_index:03d}"
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        add_jd_artifact(stack.session_repository, session_id=session_id, artifact_id=jd_artifact_id)
        _seed_retrieval_products(
            stack=stack,
            session_id=session_id,
            resume_artifact_id=resume_artifact_id,
            jd_artifact_id=jd_artifact_id,
        )
        stack.session_repository.set_active_artifact_ids(session_id, [resume_artifact_id, jd_artifact_id])

        report.turns.append(
            _run_chat_service_turn(
                stack=stack,
                session_id=session_id,
                name="LangGraph发起并等待来源选择",
                message=(
                    "根据已有材料生成一篇星河智能二面 RAG 面试复盘笔记。"
                    "先让我选择使用哪些来源，再保存成笔记。"
                ),
                max_tool_rounds=max_tool_rounds,
                run_index=run_index,
                progress=progress,
            )
        )
        source_payload = _latest_workflow_waiting_payload(
            stack=stack,
            session_id=session_id,
            payload_type="source_selection",
        )
        workflow_instance_id = _workflow_instance_id(source_payload)
        workflow_version = _workflow_version(source_payload)
        selected_ref = _first_candidate_source_ref(source_payload)
        source_resume_payload: dict[str, Any] = {
            "selected_source_refs": [selected_ref],
        }
        if scenario in {
            "interactive_rag_to_note_user_supplement",
            "interactive_rag_to_note_review_edit",
            "interactive_rag_to_note_retry_retrieval",
        }:
            source_resume_payload["user_supplement"] = (
                "补充：请重点记录 RAG 召回评估、chunk 策略和 Agent 工具权限边界。"
            )
        report.turns.append(
            _run_workflow_resume_turn(
                stack=stack,
                session_id=session_id,
                workflow_instance_id=workflow_instance_id,
                expected_version=workflow_version,
                name="LangGraph恢复到草稿确认",
                payload=source_resume_payload,
                run_index=run_index,
                progress=progress,
            )
        )
        review_payload = _latest_workflow_waiting_payload(
            stack=stack,
            session_id=session_id,
            payload_type="note_review",
        )
        workflow_version = _workflow_version(review_payload)
        if scenario == "interactive_rag_to_note_review_edit":
            review_resume_payload = {
                "action": "edit",
                "edited_draft": _edited_review_draft(review_payload),
            }
        else:
            review_resume_payload = {"action": "approve"}
        report.turns.append(
            _run_workflow_resume_turn(
                stack=stack,
                session_id=session_id,
                workflow_instance_id=workflow_instance_id,
                expected_version=workflow_version,
                name="LangGraph确认并保存笔记",
                payload=review_resume_payload,
                run_index=run_index,
                progress=progress,
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc) or exc.__class__.__name__)
        _progress(progress, scenario, run_index, f"异常：{report.errors[-1]}")
    report.elapsed_seconds = time.perf_counter() - started
    inspect_matrix_outputs(stack=stack, report=report)
    _progress(
        progress,
        scenario,
        run_index,
        f"结束：{'通过' if report.success else '失败'}，耗时 {report.elapsed_seconds:.2f}s",
    )
    return report


def _run_interactive_interview_review_scenario(
    *,
    scenario: str,
    run_index: int,
    root_data_dir: Path,
    settings: Settings,
    max_tool_rounds: int,
    stream: bool,
    progress: Callable[[str], None] | None,
) -> ScenarioReport:
    _ = stream
    langgraph_settings = settings.model_copy(
        update={
            "langgraph_workflow_enabled": True,
            "langgraph_interactive_interview_review_enabled": True,
            "langgraph_workflow_backend": "memory",
        }
    )
    run_data_dir = _prepare_clean_run_data_dir(root_data_dir / scenario, run_index)
    stack = build_live_stack(data_dir=run_data_dir, settings=langgraph_settings)
    if stack.chat_service is None:
        raise RuntimeError("ChatService is required for interactive LangGraph smoke.")
    session_id = f"sess_live_{scenario}_{run_index:03d}_{uuid4().hex[:8]}"
    report = ScenarioReport(
        scenario=scenario,
        tier=_scenario_tier(scenario),
        run_index=run_index,
        session_id=session_id,
        data_dir=run_data_dir,
        success=False,
        elapsed_seconds=0.0,
    )
    started = time.perf_counter()
    try:
        stack.session_repository.create_session(session_id)
        stack.session_repository.update_session_title(session_id, f"M60 {scenario}")
        resume_artifact_id = f"artifact_resume_interview_{run_index:03d}"
        jd_artifact_id = f"artifact_jd_interview_{run_index:03d}"
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        add_jd_artifact(stack.session_repository, session_id=session_id, artifact_id=jd_artifact_id)
        _seed_retrieval_products(
            stack=stack,
            session_id=session_id,
            resume_artifact_id=resume_artifact_id,
            jd_artifact_id=jd_artifact_id,
        )
        stack.session_repository.set_active_artifact_ids(session_id, [resume_artifact_id, jd_artifact_id])

        report.turns.append(
            _run_chat_service_turn(
                stack=stack,
                session_id=session_id,
                name="LangGraph发起并等待面试复盘范围确认",
                message=(
                    "我刚面完星河智能 AI 应用开发岗位的一面。请把这次面试复盘保存成一条 Note，"
                    "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
                    "面试里问到了 RAG chunk 策略、向量召回评估、Celery 延迟队列和 Agent 工具权限边界。"
                ),
                max_tool_rounds=max_tool_rounds,
                run_index=run_index,
                progress=progress,
            )
        )
        scope_payload = _latest_workflow_waiting_payload(
            stack=stack,
            session_id=session_id,
            payload_type="interview_review_scope",
        )
        workflow_instance_id = _workflow_instance_id(scope_payload)
        workflow_version = _workflow_version(scope_payload)
        selected_application_id = _first_application_candidate_id(scope_payload)
        scope_resume_payload: dict[str, Any] = {
            "selected_application_id": selected_application_id,
            "save_note": True,
            "update_application": True,
            "update_fields": ["stage", "risks", "next_actions", "notes"],
        }
        if scenario in {
            "interactive_interview_review_user_supplement",
            "interactive_interview_review_review_edit",
        }:
            scope_resume_payload["user_supplement"] = (
                "补充：回答 chunk 策略时需要强调按语义边界切分、保留标题层级，"
                "召回评估要讲 hit rate、precision 和人工抽检闭环。"
            )
        report.turns.append(
            _run_workflow_resume_turn(
                stack=stack,
                session_id=session_id,
                workflow_instance_id=workflow_instance_id,
                expected_version=workflow_version,
                name="LangGraph恢复到复盘草稿确认",
                payload=scope_resume_payload,
                run_index=run_index,
                progress=progress,
            )
        )
        confirmation_payload = _latest_workflow_waiting_payload(
            stack=stack,
            session_id=session_id,
            payload_type="interview_review_confirmation",
        )
        workflow_version = _workflow_version(confirmation_payload)
        if scenario == "interactive_interview_review_review_edit":
            confirmation_resume_payload = _edited_interview_review_payload(confirmation_payload)
        else:
            confirmation_resume_payload = {"action": "approve"}
        report.turns.append(
            _run_workflow_resume_turn(
                stack=stack,
                session_id=session_id,
                workflow_instance_id=workflow_instance_id,
                expected_version=workflow_version,
                name="LangGraph确认并写入面试复盘",
                payload=confirmation_resume_payload,
                run_index=run_index,
                progress=progress,
            )
        )
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc) or exc.__class__.__name__)
        _progress(progress, scenario, run_index, f"异常：{report.errors[-1]}")
    report.elapsed_seconds = time.perf_counter() - started
    inspect_matrix_outputs(stack=stack, report=report)
    _progress(
        progress,
        scenario,
        run_index,
        f"结束：{'通过' if report.success else '失败'}，耗时 {report.elapsed_seconds:.2f}s",
    )
    return report


def _run_chat_service_turn(
    *,
    stack: LiveStack,
    session_id: str,
    name: str,
    message: str,
    max_tool_rounds: int,
    run_index: int,
    progress: Callable[[str], None] | None,
) -> TurnReport:
    if stack.chat_service is None:
        raise RuntimeError("ChatService is not enabled.")
    before_counts = tool_call_counts(stack.session_repository, session_id)
    started = time.perf_counter()
    _progress(progress, "matrix", run_index, f"阶段开始：{name}")
    answer = asyncio.run(
        _consume_chat_stream(
            stack.chat_service.chat_stream(
                ChatRequest(
                    session_id=session_id,
                    message=message,
                    skill_names=["base", "tools", "memory", "file-reader"],
                    max_tool_rounds=max_tool_rounds,
                    trace_level="verbose",
                )
            )
        )
    )
    elapsed = time.perf_counter() - started
    after_counts = tool_call_counts(stack.session_repository, session_id)
    tool_calls = _diff_tool_calls(before_counts, after_counts)
    _progress(progress, "matrix", run_index, f"阶段完成：{name}，耗时 {elapsed:.2f}s，tools={tool_calls}")
    return TurnReport(name=name, answer=answer, elapsed_seconds=elapsed, tool_calls=tool_calls)


def _run_workflow_resume_turn(
    *,
    stack: LiveStack,
    session_id: str,
    workflow_instance_id: str,
    expected_version: int,
    name: str,
    payload: dict[str, Any],
    run_index: int,
    progress: Callable[[str], None] | None,
) -> TurnReport:
    if stack.chat_service is None:
        raise RuntimeError("ChatService is not enabled.")
    before_counts = tool_call_counts(stack.session_repository, session_id)
    started = time.perf_counter()
    _progress(progress, "matrix", run_index, f"阶段开始：{name}")
    answer = asyncio.run(
        _consume_chat_stream(
            stack.chat_service.resume_workflow_stream(
                workflow_instance_id,
                WorkflowResumeStreamRequest(
                    session_id=session_id,
                    payload=payload,
                    expected_version=expected_version,
                    trace_level="verbose",
                ),
            )
        )
    )
    elapsed = time.perf_counter() - started
    after_counts = tool_call_counts(stack.session_repository, session_id)
    tool_calls = _diff_tool_calls(before_counts, after_counts)
    _progress(progress, "matrix", run_index, f"阶段完成：{name}，耗时 {elapsed:.2f}s，tools={tool_calls}")
    return TurnReport(name=name, answer=answer, elapsed_seconds=elapsed, tool_calls=tool_calls)


async def _consume_chat_stream(stream: Any) -> str:
    answer = ""
    async for item in stream:
        event = item.get("event") if isinstance(item, dict) else None
        data = item.get("data") if isinstance(item, dict) else None
        if event == "error":
            detail = data.get("detail") if isinstance(data, dict) else None
            raise RuntimeError(str(detail or "chat stream error"))
        if event == "done" and isinstance(data, dict):
            raw_answer = data.get("answer")
            if isinstance(raw_answer, str):
                answer = raw_answer
    return answer


def _latest_workflow_waiting_payload(*, stack: LiveStack, session_id: str, payload_type: str) -> dict[str, Any]:
    for event in reversed(stack.session_repository.list_events(session_id)):
        if event.type != "workflow_waiting_for_input":
            continue
        payload = event.payload
        if isinstance(payload, dict) and payload.get("type") == payload_type:
            return payload
    raise RuntimeError(f"missing workflow_waiting_for_input payload: {payload_type}")


def _workflow_instance_id(payload: dict[str, Any]) -> str:
    value = payload.get("workflow_instance_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError("workflow_waiting_for_input payload missing workflow_instance_id")


def _workflow_version(payload: dict[str, Any]) -> int:
    value = payload.get("workflow_version")
    if isinstance(value, int) and value > 0:
        return value
    raise RuntimeError("workflow_waiting_for_input payload missing workflow_version")


def _first_candidate_source_ref(payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("source_selection interrupt did not include candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise RuntimeError("source_selection candidate is invalid")
    source_ref = first.get("source_ref")
    if not isinstance(source_ref, dict):
        raise RuntimeError("source_selection candidate missing source_ref")
    output = dict(source_ref)
    if isinstance(first.get("title"), str):
        output["title"] = first["title"]
    if isinstance(first.get("snippet"), str):
        output["quote"] = first["snippet"]
    return output


def _first_application_candidate_id(payload: dict[str, Any]) -> str:
    candidates = payload.get("application_candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            application_id = item.get("application_id")
            if isinstance(application_id, str) and application_id.strip():
                return application_id.strip()
    source_candidates = payload.get("source_candidates")
    if isinstance(source_candidates, list):
        for item in source_candidates:
            if not isinstance(item, dict):
                continue
            raw_ref = item.get("source_ref")
            ref = raw_ref if isinstance(raw_ref, dict) else {}
            if ref.get("source_type") != "career_application":
                continue
            source_id = ref.get("source_id")
            if isinstance(source_id, str) and source_id.strip():
                return source_id.strip()
    raise RuntimeError("interview_review_scope interrupt did not include a career application candidate")


def _edited_review_draft(payload: dict[str, Any]) -> dict[str, Any]:
    raw_draft = payload.get("draft")
    draft = raw_draft if isinstance(raw_draft, dict) else {}
    title = str(draft.get("title") or "星河智能 RAG 面试复盘").strip()
    body = str(draft.get("body_markdown") or "").strip()
    if body:
        body = body + "\n\n## 用户补充\n已人工确认：重点补强 RAG 评估指标和 Agent 工具权限边界。"
    else:
        body = "# 星河智能 RAG 面试复盘\n\n重点补强 RAG 评估指标和 Agent 工具权限边界。"
    return {
        "title": title,
        "body_markdown": body,
        "summary": "已编辑确认的 RAG 面试复盘。",
        "tags": ["星河智能", "RAG", "面试复盘"],
    }


def _edited_interview_review_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw_draft = payload.get("note_draft")
    draft = raw_draft if isinstance(raw_draft, dict) else {}
    title = str(draft.get("title") or "星河智能一面复盘").strip()
    body = str(draft.get("body_markdown") or "").strip()
    edit_line = "已人工确认：补强 RAG 评估闭环和 Agent 工具权限边界表达。"
    if body:
        body = f"{body}\n\n## 用户确认\n{edit_line}"
    else:
        body = f"# 星河智能一面复盘\n\n{edit_line}"
    return {
        "action": "edit",
        "edited_note_draft": {
            "title": title,
            "body_markdown": body,
            "summary": "已编辑确认的星河智能一面复盘。",
            "tags": ["星河智能", "一面", "RAG", "Agent"],
        },
        "edited_application_updates": {
            "stage": "interviewing",
            "next_actions": ["补强 RAG 评估指标表达", "复盘 Celery 延迟队列设计", "整理 Agent 工具权限边界案例"],
            "risks": ["RAG 评估闭环表达需要更体系化"],
            "notes": "一面后已确认：下一轮重点准备 RAG 评估、Celery 队列和工具权限边界。",
        },
    }


def _setup_simple_scenario(*, stack: LiveStack, scenario: str, session_id: str, run_index: int) -> None:
    if scenario == "main_resume_child":
        resume_artifact_id = f"artifact_resume_matrix_{run_index:03d}"
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        stack.session_repository.set_active_artifact_ids(session_id, [resume_artifact_id])
        return
    if scenario == "main_job_child":
        resume_artifact_id = f"artifact_resume_matrix_{run_index:03d}"
        jd_artifact_id = f"artifact_jd_matrix_{run_index:03d}"
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        add_jd_artifact(stack.session_repository, session_id=session_id, artifact_id=jd_artifact_id)
        _seed_resume_products(stack=stack, session_id=session_id, resume_artifact_id=resume_artifact_id)
        stack.session_repository.set_active_artifact_ids(session_id, [jd_artifact_id])
        return
    if scenario == "rag_read_only":
        resume_artifact_id = f"artifact_resume_matrix_{run_index:03d}"
        jd_artifact_id = f"artifact_jd_matrix_{run_index:03d}"
        add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
        add_jd_artifact(stack.session_repository, session_id=session_id, artifact_id=jd_artifact_id)
        _seed_retrieval_products(
            stack=stack,
            session_id=session_id,
            resume_artifact_id=resume_artifact_id,
            jd_artifact_id=jd_artifact_id,
        )


def _simple_scenario_turns(scenario: str, *, run_index: int) -> list[ScenarioTurnSpec]:
    if scenario == "chat_only":
        return [
            ScenarioTurnSpec(
                name="仅聊天",
                message="用两句话解释 RAG 和普通关键词搜索的区别。不要保存任何内容，也不要调用工具。",
                skill_names=("base",),
            )
        ]
    if scenario == "memory_write":
        return [
            ScenarioTurnSpec(
                name="记忆写入",
                message="请记住：我长期优先投 AI 应用后端岗位，城市优先上海和杭州。不要保存成笔记。",
            )
        ]
    if scenario == "note_write":
        return [
            ScenarioTurnSpec(
                name="笔记写入",
                message=(
                    "请把下面内容保存为一条可编辑笔记，标题叫 RAG 面试准备摘记："
                    "RAG 面试要重点准备 chunk 策略、召回评估、失败恢复和 Agent 工具权限边界。"
                    "这不是长期偏好，不要写 memory。"
                ),
            )
        ]
    if scenario == "rag_read_only":
        return [
            ScenarioTurnSpec(
                name="RAG只读召回",
                message=(
                    "根据之前保存的星河智能 AI 应用开发岗位资料，帮我准备二面。"
                    "请先召回相关上下文再回答；这轮只读，不要保存笔记、不要写 memory、不要创建学习任务。"
                ),
            )
        ]
    if scenario == "main_resume_child":
        return [
            ScenarioTurnSpec(
                name="Main+ResumeAgent",
                message=(
                    f"我上传了一份简历，artifact_id 是 artifact_resume_matrix_{run_index:03d}。"
                    "请委派 resume_agent 读取这份简历，生成诊断 artifact，并保存结构化 ResumeProfile。"
                    "这轮不要分析 JD，不要创建求职项目，不要生成定制简历。"
                ),
            )
        ]
    if scenario == "main_job_child":
        return [
            ScenarioTurnSpec(
                name="Main+JobAgent",
                message=(
                    f"已有 ResumeProfile 和职业画像，目标 JD artifact_id 是 artifact_jd_matrix_{run_index:03d}。"
                    "请委派 job_agent 基于这个 JD 和已有画像生成 JDAnalysis 与 JobFitReport。"
                    "这轮不要创建 CareerApplication，不要生成 ResumeVersion。"
                ),
            )
        ]
    raise ValueError(f"Unsupported simple scenario: {scenario}")


def _run_turn(
    *,
    stack: LiveStack,
    session_id: str,
    turn: ScenarioTurnSpec,
    max_tool_rounds: int,
    run_index: int,
    stream: bool,
    progress: Callable[[str], None] | None,
) -> TurnReport:
    before_counts = tool_call_counts(stack.session_repository, session_id)
    started = time.perf_counter()
    _progress(progress, "matrix", run_index, f"阶段开始：{turn.name}")
    run_input = AgentRunInput(
        session_id=session_id,
        user_message=turn.message,
        skill_names=list(turn.skill_names),
        max_tool_rounds=max_tool_rounds,
        context=_run_context(session_id),
    )
    if stream:
        output = asyncio.run(stack.runtime.run_stream(run_input, _DiscardingEventChannel()))
    else:
        output = stack.runtime.run(run_input)
    elapsed = time.perf_counter() - started
    after_counts = tool_call_counts(stack.session_repository, session_id)
    tool_calls = _diff_tool_calls(before_counts, after_counts)
    _progress(progress, "matrix", run_index, f"阶段完成：{turn.name}，耗时 {elapsed:.2f}s，tools={tool_calls}")
    return TurnReport(name=turn.name, answer=output.answer, elapsed_seconds=elapsed, tool_calls=tool_calls)


def _apply_common_gates(*, stack: LiveStack, report: ScenarioReport) -> None:
    if internal_runtime_answer_detected(stack.session_repository, report.session_id):
        report.errors.append("assistant_message 泄露内部 runtime 文案。")
    if unusable_final_answer_detected(stack.session_repository, report.session_id):
        report.errors.append("assistant_message/agent_result_summary 包含伪工具调用或不可交付弱答复。")
    if hard_safety_limit_detected(stack.session_repository, report.session_id):
        report.errors.append("触发 hard safety 上限收束。")
    if tool_loop_stagnation_detected(stack.session_repository, report.session_id):
        report.errors.append("触发无推进工具循环收束。")
    if path_argument_leaked(stack.session_repository, report.session_id):
        report.errors.append("工具参数中出现 path/file_path/workspace_path。")


def _apply_scenario_gates(report: ScenarioReport) -> None:
    if report.scenario == "chat_only":
        if report.tool_call_counts:
            report.errors.append(f"chat_only 不应调用工具，实际 tools={sorted(report.tool_call_counts)}。")
        return
    if report.scenario == "memory_write":
        _require_tool(report, "memory_write")
        _forbid_tools(report, {"note_create", "note_append"})
        return
    if report.scenario == "note_write":
        if not _has_any_tool(report, {"note_create", "note_append"}):
            report.errors.append("note_write 应调用 note_create 或 note_append。")
        _forbid_tools(report, {"memory_write"})
        if report.record_counts.get("notes", 0) < 1:
            report.errors.append("note_write 未产生 Note 记录。")
        return
    if report.scenario == "rag_read_only":
        _require_tool(report, "retrieval_search")
        _require_tool(report, "retrieval_context_pack")
        _forbid_write_tools(report)
        return
    if report.scenario == "main_resume_child":
        _require_tool(report, "delegate_agents")
        _require_min_record_count(report, "resume_profiles", 1)
        _forbid_record_counts(report, {"jd_analyses", "job_fit_reports", "career_applications", "resume_versions"})
        return
    if report.scenario == "main_job_child":
        _require_tool(report, "delegate_agents")
        _require_min_record_count(report, "jd_analyses", 1)
        _require_min_record_count(report, "job_fit_reports", 1)
        _forbid_record_counts(report, {"career_applications", "resume_versions"})
        return
    if report.scenario in INTERACTIVE_RAG_TO_NOTE_SCENARIOS:
        _require_tool(report, "retrieval_search")
        _require_tool(report, "retrieval_context_pack")
        note_writes = report.tool_call_counts.get("note_create", 0) + report.tool_call_counts.get("note_append", 0)
        if note_writes < 1:
            report.errors.append(f"{report.scenario} 应调用 note_create 或 note_append。")
        if note_writes > 1:
            report.errors.append(f"{report.scenario} note_create/note_append 不应超过 1 次，actual={note_writes}。")
        _forbid_tools(report, {"memory_write", "career_application_create", "career_application_merge"})
        _require_min_record_count(report, "notes", 1)
        waiting_count = report.workflow_event_counts.get("workflow_waiting_for_input", 0)
        if waiting_count < 2:
            report.errors.append(f"{report.scenario} 应至少产生两次 workflow_waiting_for_input，actual={waiting_count}。")
        if report.workflow_event_counts.get("workflow_completed", 0) < 1:
            report.errors.append(f"{report.scenario} 缺少 workflow_completed 事件。")
        return
    if report.scenario in INTERACTIVE_INTERVIEW_REVIEW_SCENARIOS:
        _require_tool(report, "retrieval_search")
        _require_tool(report, "retrieval_context_pack")
        _require_exact_tool(report, "note_create", 1)
        _require_exact_tool(report, "career_application_merge", 1)
        _forbid_tools(
            report,
            {
                "career_application_create",
                "career_jd_analysis_save",
                "career_job_fit_report_save",
                "career_profile_merge",
                "career_resume_version_create",
                "delegate_agents",
                "learning_task_create",
                "memory_write",
                "note_append",
            },
        )
        _require_min_record_count(report, "notes", 2)
        _require_min_record_count(report, "career_applications", 1)
        waiting_count = report.workflow_event_counts.get("workflow_waiting_for_input", 0)
        if waiting_count < 2:
            report.errors.append(f"{report.scenario} 应至少产生两次 workflow_waiting_for_input，actual={waiting_count}。")
        if report.workflow_event_counts.get("workflow_completed", 0) < 1:
            report.errors.append(f"{report.scenario} 缺少 workflow_completed 事件。")
        if report.workflow_event_counts.get("workflow_failed", 0) > 0:
            report.errors.append(f"{report.scenario} 出现 workflow_failed 事件。")
        return


def _apply_live_quality_gate(*, stack: LiveStack, report: ScenarioReport) -> None:
    quality_report = check_career_live_quality(
        repository=stack.session_repository,
        career_store=stack.career_store,
        session_id=report.session_id,
    )
    for finding in quality_report.findings:
        if finding.severity != "error":
            continue
        if finding.code not in report.quality_error_codes:
            report.quality_error_codes.append(finding.code)
        report.errors.append(f"Live 质量门禁错误: {finding.format()}")


def _apply_product_stop_line(report: ScenarioReport) -> None:
    harmful_duplicates = _int_value(report.efficiency.get("harmful_duplicate_tool_call_count")) or 0
    if harmful_duplicates > 0:
        _append_unique_error(report, f"出现有害重复工具调用: count={harmful_duplicates}。")

    hidden_results = _int_value(report.efficiency.get("hidden_tool_result_count")) or 0
    if hidden_results > 0:
        _append_unique_error(report, f"出现 hidden/runtime-hidden 工具结果: count={hidden_results}。")

    if "unrecovered_failed_tool_result_count" in report.efficiency:
        failed_results = _int_value(report.efficiency.get("unrecovered_failed_tool_result_count")) or 0
        failed_tools = report.efficiency.get("unrecovered_failed_tool_results")
    else:
        failed_results = _int_value(report.efficiency.get("failed_tool_result_count")) or 0
        failed_tools = report.efficiency.get("failed_tool_results")
    if failed_results > 0:
        _append_unique_error(report, f"出现失败工具结果: count={failed_results} tools={_compact_json(failed_tools)}。")

    decisions = report.efficiency.get("workflow_decisions")
    if isinstance(decisions, dict):
        blocking = {key: decisions.get(key) for key in sorted(_BLOCKING_WORKFLOW_DECISIONS) if decisions.get(key)}
        if blocking:
            _append_unique_error(report, f"触发阻断型 workflow runtime decision: {_compact_json(blocking)}。")

    if (_int_value(report.retrieval_quality.get("budget_violations")) or 0) > 0:
        _append_unique_error(report, "RAG 召回上下文超过 max_chars 预算。")

    _apply_cost_warning_line(report)


def _apply_cost_warning_line(report: ScenarioReport) -> None:
    if report.tier != "P0":
        return
    limits = _P0_COST_WARNING_LIMITS.get(report.scenario)
    if not limits:
        return
    elapsed_limit = limits["elapsed_seconds"]
    if report.elapsed_seconds > elapsed_limit:
        _append_unique_warning(
            report,
            f"P0 成本提醒: elapsed_seconds={report.elapsed_seconds:.2f} 超过建议线 {elapsed_limit}s。",
        )
    token_limit = limits["total_llm_tokens"]
    total_tokens = _int_value(report.efficiency.get("total_llm_tokens")) or 0
    if total_tokens > token_limit:
        _append_unique_warning(
            report,
            f"P0 成本提醒: total_llm_tokens={total_tokens} 超过建议线 {token_limit}。",
        )
    call_limit = limits["total_llm_calls"]
    total_calls = _int_value(report.efficiency.get("total_llm_calls")) or 0
    if total_calls > call_limit:
        _append_unique_warning(
            report,
            f"P0 成本提醒: total_llm_calls={total_calls} 超过建议线 {call_limit}。",
        )


def _append_unique_error(report: ScenarioReport, message: str) -> None:
    if message not in report.errors:
        report.errors.append(message)


def _append_unique_warning(report: ScenarioReport, message: str) -> None:
    if message not in report.warnings:
        report.warnings.append(message)


def _forbid_write_tools(report: ScenarioReport) -> None:
    if report.write_tool_counts:
        report.errors.append(f"{report.scenario} 不应调用写入工具，实际 write_tools={report.write_tool_counts}。")


def _require_tool(report: ScenarioReport, tool_name: str) -> None:
    if report.tool_call_counts.get(tool_name, 0) < 1:
        report.errors.append(f"{report.scenario} 应调用 {tool_name}。")


def _require_exact_tool(report: ScenarioReport, tool_name: str, count: int) -> None:
    actual = report.tool_call_counts.get(tool_name, 0)
    if actual != count:
        report.errors.append(f"{report.scenario} 应调用 {tool_name} {count} 次，actual={actual}。")


def _has_any_tool(report: ScenarioReport, tool_names: set[str]) -> bool:
    return any(report.tool_call_counts.get(name, 0) > 0 for name in tool_names)


def _forbid_tools(report: ScenarioReport, tool_names: set[str]) -> None:
    leaked = sorted(name for name in tool_names if report.tool_call_counts.get(name, 0) > 0)
    if leaked:
        report.errors.append(f"{report.scenario} 出现越界工具调用: {leaked}。")


def _require_min_record_count(report: ScenarioReport, key: str, count: int) -> None:
    if report.record_counts.get(key, 0) < count:
        report.errors.append(f"{report.scenario} 缺少产品记录 {key}: expected>={count} actual={report.record_counts.get(key, 0)}。")


def _forbid_record_counts(report: ScenarioReport, keys: set[str]) -> None:
    leaked = {key: report.record_counts.get(key, 0) for key in sorted(keys) if report.record_counts.get(key, 0) > 0}
    if leaked:
        report.errors.append(f"{report.scenario} 出现越界产品记录: {leaked}。")


def _require_record_counts(
    *,
    scenario: str,
    record_counts: dict[str, int],
    errors: list[str],
    required: dict[str, int],
) -> None:
    for key, expected in required.items():
        actual = record_counts.get(key, 0)
        if actual < expected:
            errors.append(f"{scenario} 缺少产品记录 {key}: expected>={expected} actual={actual}。")


def _record_counts_for_session(*, stack: LiveStack, session_id: str) -> dict[str, int]:
    return {
        "resume_profiles": sum(
            1 for item in stack.career_store.list_resume_profiles(include_archived=True) if item.source_session_id == session_id
        ),
        "career_profiles": sum(
            1 for item in stack.career_store.list_career_profiles(include_archived=True) if item.source_session_id == session_id
        ),
        "jd_analyses": sum(
            1 for item in stack.career_store.list_jd_analyses(include_archived=True) if item.source_session_id == session_id
        ),
        "job_fit_reports": sum(
            1 for item in stack.career_store.list_job_fit_reports(include_archived=True) if item.source_session_id == session_id
        ),
        "career_applications": sum(
            1 for item in stack.career_store.list_career_applications(include_archived=True) if item.source_session_id == session_id
        ),
        "resume_versions": sum(
            1 for item in stack.career_store.list_resume_versions(include_archived=True) if item.source_session_id == session_id
        ),
        "notes": sum(
            1 for item in stack.note_store.list_notes(include_archived=True) if item.source_session_id == session_id
        ),
        "learning_tasks": sum(
            1
            for item in stack.learning_store.list_learning_tasks(include_archived=True)
            if item.source_session_id == session_id
        ),
    }


def _workflow_event_counts(*, stack: LiveStack, session_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in stack.session_repository.list_events(session_id):
        if not event.type.startswith("workflow_"):
            continue
        counts[event.type] = counts.get(event.type, 0) + 1
    return counts


def _seed_resume_products(*, stack: LiveStack, session_id: str, resume_artifact_id: str) -> None:
    now = app_now()
    stack.career_store.save_resume_profile(
        ResumeProfile(
            resume_profile_id=f"resume_profile_matrix_{uuid4().hex[:8]}",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=resume_artifact_id,
            evidence_refs=[resume_artifact_id],
            created_at=now,
            updated_at=now,
            basic_info={"name": "张三", "target_role": "AI 应用开发工程师"},
            project_experience=["简历诊断 Agent，多 Agent 委派，RAG 与工具调用审计。"],
            skills=["Python", "FastAPI", "RAG", "Agent Runtime"],
            diagnosis={"summary": "后端和 Agent 工程经验匹配 AI 应用岗位。"},
        )
    )
    stack.career_store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=resume_artifact_id,
            evidence_refs=[resume_artifact_id],
            created_at=now,
            updated_at=now,
            career_goal="AI 应用开发 / 后端工程师",
            target_roles=["AI 应用开发工程师", "后端工程师"],
            strengths=["Python 后端", "Agent 工具调用"],
            weaknesses=["RAG 评估指标表达需要加强"],
            skills=["Python", "FastAPI", "RAG", "Agent Runtime"],
        )
    )


def _seed_retrieval_products(
    *,
    stack: LiveStack,
    session_id: str,
    resume_artifact_id: str,
    jd_artifact_id: str,
) -> None:
    _seed_resume_products(stack=stack, session_id=session_id, resume_artifact_id=resume_artifact_id)
    now = app_now()
    jd = stack.career_store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id=f"jd_matrix_{uuid4().hex[:8]}",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=jd_artifact_id,
            evidence_refs=[jd_artifact_id],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI 应用开发工程师",
            required_skills=["Python", "FastAPI", "RAG", "Agent 工程"],
            responsibilities=["建设 RAG 与 Agent Runtime 后端服务"],
            keywords=["RAG", "Agent Runtime", "向量检索"],
            interview_focus=["chunk 策略", "召回评估", "工具权限边界"],
        )
    )
    resume = stack.career_store.list_resume_profiles(include_archived=True)[-1]
    fit = stack.career_store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id=f"fit_matrix_{uuid4().hex[:8]}",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=jd_artifact_id,
            evidence_refs=[resume_artifact_id, jd_artifact_id, resume.resume_profile_id, jd.jd_analysis_id],
            created_at=now,
            updated_at=now,
            jd_analysis_id=jd.jd_analysis_id,
            resume_profile_id=resume.resume_profile_id,
            career_profile_id="career_profile_default",
            overall_score=82,
            score_breakdown={"backend": 86, "rag": 78, "agent": 84},
            matched_evidence=["Python/FastAPI 后端经验", "Agent 工具调用项目经验"],
            gaps=["RAG 评估指标需要更强表达"],
            resume_optimization_direction=["补充 RAG 评估闭环"],
            interview_preparation_focus=["chunk 策略", "precision/recall/hit rate", "权限边界"],
            recommendation="recommended",
        )
    )
    application = stack.career_store.save_career_application(
        CareerApplication(
            application_id=f"application_matrix_{uuid4().hex[:8]}",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=jd_artifact_id,
            evidence_refs=[resume_artifact_id, jd_artifact_id, resume.resume_profile_id, jd.jd_analysis_id, fit.job_fit_report_id],
            created_at=now,
            updated_at=now,
            company="星河智能",
            position="AI 应用开发工程师",
            location="上海",
            stage="interviewing",
            priority="high",
            resume_profile_id=resume.resume_profile_id,
            career_profile_id="career_profile_default",
            jd_analysis_id=jd.jd_analysis_id,
            job_fit_report_id=fit.job_fit_report_id,
            summary="星河智能 AI 应用开发岗位进入二面准备阶段。",
            next_actions=["准备 RAG 召回评估", "复盘 Agent Runtime 工具权限边界"],
            risks=["RAG 评估指标表达不够体系化"],
            notes="二面重点是 RAG、Agent Runtime 和后端工程化。",
        )
    )
    stack.note_store.save_note(
        Note(
            note_id=f"note_matrix_{uuid4().hex[:8]}",
            status=NoteRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=[application.application_id, fit.job_fit_report_id],
            created_at=now,
            updated_at=now,
            title="星河智能二面准备记录",
            body_markdown="RAG 面试重点：chunk 策略、召回评估、失败恢复、Agent 工具权限边界。",
            note_type=NoteType.NOTE,
            tags=["星河智能", "二面", "RAG"],
            source_refs=[
                NoteSourceRef(
                    source_type=NoteSourceType.CAREER_APPLICATION,
                    source_id=application.application_id,
                    source_session_id=session_id,
                    title="星河智能 AI 应用开发工程师",
                )
            ],
            related_application_id=application.application_id,
            summary="二面准备聚焦 RAG 评估和 Agent Runtime。",
            origin=NoteOrigin.AGENT,
        )
    )


def _run_context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_matrix_{uuid4().hex[:12]}",
        agent_id="agent_main",
        turn_id=f"turn_matrix_{uuid4().hex[:12]}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={"verbose": True},
    )


def _diff_tool_calls(before: dict[str, int], after: dict[str, int]) -> list[str]:
    output: list[str] = []
    for name in sorted(after):
        output.extend([name] * max(0, after[name] - before.get(name, 0)))
    return output


async def run_all(args: argparse.Namespace) -> list[ScenarioReport]:
    settings = Settings.load()
    root_data_dir = Path(args.data_dir)
    root_data_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(args.concurrency)
    scenarios = _selected_scenarios(args)
    if not args.quiet:
        print(_runtime_config_text(settings), flush=True)
        print(f"scenarios={','.join(scenarios)}", flush=True)

    def progress(message: str) -> None:
        if args.quiet:
            return
        print(f"[{to_app_iso(app_now())}] {message}", flush=True)

    work_items = [(scenario, run_index) for scenario in scenarios for run_index in range(1, args.runs + 1)]

    async def run_one(scenario: str, run_index: int) -> ScenarioReport:
        async with semaphore:
            return await asyncio.to_thread(
                run_matrix_scenario,
                scenario=scenario,
                run_index=run_index,
                root_data_dir=root_data_dir,
                settings=settings,
                max_tool_rounds=args.max_tool_rounds,
                stream=getattr(args, "stream", False),
                progress=progress,
            )

    tasks = [asyncio.create_task(run_one(scenario, run_index)) for scenario, run_index in work_items]
    return await asyncio.gather(*tasks)


def print_report(reports: list[ScenarioReport]) -> None:
    print()
    print("=== Live Smoke Matrix 报告 ===")
    if not reports:
        print("没有执行任何 scenario。")
        return
    elapsed_values = [item.elapsed_seconds for item in reports]
    print(f"运行数: {len(reports)}")
    print(f"成功数: {sum(1 for item in reports if item.success)}")
    print(f"失败数: {sum(1 for item in reports if not item.success)}")
    print(f"平均耗时: {statistics.fmean(elapsed_values):.2f}s")
    print(f"最大耗时: {max(elapsed_values):.2f}s")
    print(_aggregate_efficiency_text(reports))
    print()
    for item in reports:
        status = "通过" if item.success else "失败"
        print(f"--- {item.scenario} Run {item.run_index}: {status} ---")
        print(f"tier: {item.tier}")
        print(f"session_id: {item.session_id}")
        print(f"data_dir: {item.data_dir}")
        print(f"elapsed: {item.elapsed_seconds:.2f}s")
        for turn in item.turns:
            print(f"  [{turn.name}] {turn.elapsed_seconds:.2f}s tools={_preview_list(turn.tool_calls, limit=8)}")
            print(f"    answer_preview: {_compact_text(turn.answer, 120)}")
        print(f"  record_counts: {_compact_json(item.record_counts)}")
        print(f"  artifact_count: {item.artifact_count}")
        print(f"  tool_call_counts: {_compact_json(item.tool_call_counts)}")
        print(f"  write_tool_counts: {_compact_json(item.write_tool_counts)}")
        if item.efficiency:
            print(
                "  efficiency: "
                f"llm_calls={item.efficiency.get('total_llm_calls', 0)} "
                f"tokens={item.efficiency.get('total_llm_tokens', 0)} "
                f"duplicates={item.efficiency.get('duplicate_tool_call_count', 0)} "
                f"harmful_duplicates={item.efficiency.get('harmful_duplicate_tool_call_count', 0)} "
                f"hidden={item.efficiency.get('hidden_tool_result_count', 0)} "
                f"final_answer_recovery={item.efficiency.get('final_answer_recovery_tokens', 0)}/"
                f"{item.efficiency.get('final_answer_recovery_calls', 0)} "
                f"finalization_packet={item.efficiency.get('finalization_packet_used_count', 0)}/"
                f"{item.efficiency.get('finalization_packet_count', 0)} "
                f"packet_tokens={item.efficiency.get('finalization_packet_estimate_tokens', 0)}"
            )
        if item.retrieval_quality:
            print(
                "  retrieval: "
                f"search={item.retrieval_quality.get('search_calls', 0)} "
                f"context_pack={item.retrieval_quality.get('context_pack_calls', 0)} "
                f"budget_violations={item.retrieval_quality.get('budget_violations', 0)}"
            )
        if item.workflow_event_counts:
            print(f"  workflow_event_counts: {_compact_json(item.workflow_event_counts)}")
        if item.warnings:
            print(f"  warnings: {_preview_list(item.warnings, limit=4)}")
        if item.errors:
            print(f"  errors: {_preview_list(item.errors, limit=5)}")
        if item.last_events:
            print("  last_events:")
            for event in item.last_events:
                print(f"    - {event}")
        print()


def write_json_report(reports: list[ScenarioReport], path: Path) -> None:
    payload = []
    for report in reports:
        row = asdict(report)
        row["data_dir"] = str(report.data_dir)
        payload.append(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"reports": payload}, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行跨场景真实模型 live smoke matrix。")
    parser.add_argument("--scenario", action="append", choices=ALL_SCENARIOS, help="要运行的场景，可重复。")
    parser.add_argument("--all-p0", action="store_true", help="运行所有 P0 场景。")
    parser.add_argument("--all-p1", action="store_true", help="运行所有 P1 场景。")
    parser.add_argument("--runs", type=int, default=1, help="每个场景运行次数。")
    parser.add_argument("--concurrency", type=int, default=1, help="并发运行数。")
    parser.add_argument("--data-dir", type=Path, default=Path("data/live_smoke_matrix"), help="输出数据根目录。")
    parser.add_argument("--max-tool-rounds", type=int, default=24, help="每轮对话允许的软工具预算。")
    parser.add_argument("--json-report", type=Path, default=None, help="可选 JSON 报告输出路径。")
    parser.add_argument("--verbose", action="store_true", help="打开应用日志。")
    parser.add_argument("--quiet", action="store_true", help="关闭逐 run / 逐阶段进度输出，只打印最终报告。")
    parser.add_argument("--stream", action="store_true", help="通过 AgentRuntime.run_stream 验证真实流式入口。")
    args = parser.parse_args()
    if not args.scenario and not args.all_p0 and not args.all_p1:
        parser.error("must provide --scenario, --all-p0, or --all-p1")
    if args.runs <= 0:
        parser.error("--runs must be positive")
    if args.concurrency <= 0:
        parser.error("--concurrency must be positive")
    if args.max_tool_rounds < 1 or args.max_tool_rounds > 40:
        parser.error("--max-tool-rounds must be in range 1..40")
    return args


def _selected_scenarios(args: argparse.Namespace) -> list[str]:
    selected: list[str] = []
    if args.all_p0:
        selected.extend(P0_SCENARIOS)
    if args.all_p1:
        selected.extend(P1_SCENARIOS)
    if args.scenario:
        selected.extend(args.scenario)
    output: list[str] = []
    for item in selected:
        scenario = _normalize_scenario(item)
        if scenario not in output:
            output.append(scenario)
    return output


def _normalize_scenario(value: str) -> str:
    scenario = value.strip()
    if scenario not in ALL_SCENARIOS:
        raise ValueError(f"Unsupported scenario: {value}")
    return scenario


def _scenario_tier(scenario: str) -> str:
    if scenario in P0_SCENARIOS:
        return "P0"
    if scenario in P1_SCENARIOS:
        return "P1"
    return "P2"


def _aggregate_efficiency_text(reports: list[ScenarioReport]) -> str:
    summaries = [item.efficiency for item in reports if item.efficiency]
    if not summaries:
        return "效率摘要: unavailable"
    total_calls = [_int_value(item.get("total_llm_calls")) or 0 for item in summaries]
    total_tokens = [_int_value(item.get("total_llm_tokens")) or 0 for item in summaries]
    harmful_duplicate_runs = sum(
        1 for item in summaries if (_int_value(item.get("harmful_duplicate_tool_call_count")) or 0) > 0
    )
    hidden_runs = sum(1 for item in summaries if (_int_value(item.get("hidden_tool_result_count")) or 0) > 0)
    return (
        "效率摘要: "
        f"avg_llm_calls={statistics.fmean(total_calls):.1f} "
        f"max_llm_calls={max(total_calls)} "
        f"avg_tokens={statistics.fmean(total_tokens):.0f} "
        f"max_tokens={max(total_tokens)} "
        f"harmful_duplicate_runs={harmful_duplicate_runs}/{len(summaries)} "
        f"hidden_runs={hidden_runs}/{len(summaries)}"
    )


def _progress(progress: Callable[[str], None] | None, scenario: str, run_index: int, message: str) -> None:
    if progress is not None:
        progress(f"{scenario} Run {run_index}: {message}")


def main() -> None:
    args = parse_args()
    logging.getLogger().setLevel(logging.INFO if args.verbose else logging.CRITICAL)
    started = app_now()
    print("Live smoke matrix started:", to_app_iso(started))
    print(f"runs={args.runs} concurrency={args.concurrency} stream={args.stream} data_dir={args.data_dir}")
    reports = asyncio.run(run_all(args))
    print_report(reports)
    if args.json_report is not None:
        write_json_report(reports, args.json_report)
        print(f"JSON report: {args.json_report}")
    ended = app_now()
    print("Live smoke matrix finished:", to_app_iso(ended))
    if any(not item.success for item in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
