"""Built-in tools for learning plans and progress tracking."""

from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError, ToolExecutionError, ValidationError
from app.core.time import app_now, to_app_iso
from app.domain.models import RunContext, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository
from app.learning.models import (
    LearningPlan,
    LearningRecordStatus,
    LearningTask,
    ProgressCheckin,
    WeaknessTracker,
)
from app.learning.store import LearningStore
from app.tools.builtin_tools.common import validate_context
from app.tools.builtin_tools.session_artifact_helpers import require_session_artifact

__all__ = [
    "LearningCheckinCreateTool",
    "LearningPlanCreateTool",
    "LearningPlanGetTool",
    "LearningPlanListTool",
    "LearningTaskCreateTool",
    "LearningTaskGetTool",
    "LearningTaskListTool",
    "LearningTaskUpdateStateTool",
    "LearningWeaknessCreateTool",
    "LearningWeaknessUpdateTool",
]

_RESOURCE_REF_RE = re.compile(r"^(resource|skill_req|artifact|experience|company)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_EVIDENCE_REF_TYPE_ALIASES = {
    "application": "application",
    "application_id": "application",
    "career_application": "application",
    "career_application_id": "application",
    "artifact": "artifact",
    "artifact_id": "artifact",
    "career_profile": "career_profile",
    "career_profile_id": "career_profile",
    "checkin": "checkin",
    "checkin_id": "checkin",
    "company": "company",
    "company_id": "company",
    "experience": "experience",
    "experience_id": "experience",
    "fit": "fit",
    "fit_report": "fit",
    "job_fit_report": "fit",
    "job_fit_report_id": "fit",
    "jd": "jd",
    "jd_analysis": "jd",
    "jd_analysis_id": "jd",
    "learning_plan": "learning_plan",
    "learning_plan_id": "learning_plan",
    "learning_task": "learning_task",
    "learning_task_id": "learning_task",
    "note": "note",
    "note_id": "note",
    "question": "question",
    "question_id": "question",
    "resource": "resource",
    "resource_id": "resource",
    "resume_profile": "resume_profile",
    "resume_profile_id": "resume_profile",
    "resume_version": "resume_version",
    "resume_version_id": "resume_version",
    "review": "review",
    "review_id": "review",
    "session": "sess",
    "session_id": "sess",
    "skill_requirement": "skill_req",
    "skill_requirement_id": "skill_req",
    "weakness": "weakness",
    "weakness_id": "weakness",
}
_PLAN_UPDATE_FIELDS = {
    "description",
    "end_date",
    "evidence_refs",
    "focus_skill_tags",
    "goals",
    "plan_type",
    "priority",
    "progress_summary",
    "review_schedule_ids",
    "source_artifact_id",
    "start_date",
    "target_application_id",
    "target_company",
    "target_role",
    "task_ids",
    "title",
    "weakness_ids",
}
_TASK_UPDATE_FIELDS = {
    "completed_at",
    "description",
    "due_date",
    "estimated_minutes",
    "evidence_refs",
    "learning_plan_id",
    "note_refs",
    "output_artifact_id",
    "planned_start_date",
    "priority",
    "progress_notes",
    "question_refs",
    "resource_refs",
    "skill_tags",
    "source_artifact_id",
    "state",
    "success_criteria",
    "task_type",
    "title",
}
_WEAKNESS_UPDATE_FIELDS = {
    "description",
    "evidence_refs",
    "last_observed_at",
    "related_note_ids",
    "related_task_ids",
    "resolved_at",
    "resolution_summary",
    "severity",
    "skill_tags",
    "source_artifact_id",
    "source_report_ids",
    "state",
    "target_application_ids",
    "title",
    "weakness_type",
}
_CHECKIN_CREATE_FIELDS = {
    "blockers",
    "checkin_date",
    "checkin_id",
    "confidence",
    "evidence_refs",
    "learning_plan_id",
    "learning_task_id",
    "minutes_spent",
    "next_action",
    "note_refs",
    "progress_state",
    "source_artifact_id",
    "summary",
}


class LearningPlanCreateTool:
    """Create or reuse one learning plan."""

    def __init__(self, learning_store: LearningStore, session_repository: SessionRepository) -> None:
        self._learning_store = learning_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_plan_create",
            description=(
                "Create a user-visible learning plan when the user asks for a learning plan, interview preparation "
                "plan, or long-running skill improvement plan. This tool does not write memory or notes."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "learning_plan_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "plan_type": {
                        "type": "string",
                        "enum": ["career_gap", "interview_prep", "skill_build", "review", "custom"],
                    },
                    "target_application_id": {"type": "string"},
                    "target_role": {"type": "string"},
                    "target_company": {"type": "string"},
                    "start_date": {"type": "string"},
                    "end_date": {"type": "string"},
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "goals": {"type": "array", "items": {"type": "string"}},
                    "focus_skill_tags": {"type": "array", "items": {"type": "string"}},
                    "task_ids": {"type": "array", "items": {"type": "string"}},
                    "weakness_ids": {"type": "array", "items": {"type": "string"}},
                    "review_schedule_ids": {"type": "array", "items": {"type": "string"}},
                    "progress_summary": {"type": "string"},
                },
                "required": ["title", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _optional_prefixed_id(args.get("learning_plan_id"), "learning_plan") or _new_id(
                "learning_plan"
            )
            existing = self._learning_store.get_learning_plan(record_id)
            if existing is not None:
                return _record_result(
                    "learning_plan_create",
                    "learning_plan",
                    existing.learning_plan_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = LearningPlan(
                learning_plan_id=record_id,
                status=LearningRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=_optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    args.get("source_artifact_id"),
                    field_name="source_artifact_id",
                ),
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
                created_at=_now(),
                updated_at=_now(),
                title=_required_string(args.get("title"), field_name="title"),
                description=_optional_string(args.get("description")) or "",
                plan_type=_optional_string(args.get("plan_type")) or "custom",
                target_application_id=_optional_prefixed_id(args.get("target_application_id"), "application"),
                target_role=_optional_string(args.get("target_role")) or "",
                target_company=_optional_string(args.get("target_company")) or "",
                start_date=_optional_datetime(args.get("start_date"), field_name="start_date"),
                end_date=_optional_datetime(args.get("end_date"), field_name="end_date"),
                priority=_optional_string(args.get("priority")) or "medium",
                goals=_optional_string_list(args.get("goals"), field_name="goals"),
                focus_skill_tags=_optional_string_list(args.get("focus_skill_tags"), field_name="focus_skill_tags"),
                task_ids=_optional_prefixed_id_list(args.get("task_ids"), "learning_task", field_name="task_ids"),
                weakness_ids=_optional_prefixed_id_list(args.get("weakness_ids"), "weakness", field_name="weakness_ids"),
                review_schedule_ids=_optional_prefixed_id_list(
                    args.get("review_schedule_ids"),
                    "review",
                    field_name="review_schedule_ids",
                ),
                progress_summary=_optional_string(args.get("progress_summary")) or "",
            )
            saved = self._learning_store.save_learning_plan(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_plan_create", "learning_plan", saved.learning_plan_id, saved)


class LearningPlanGetTool:
    """Read one learning plan."""

    def __init__(self, learning_store: LearningStore) -> None:
        self._learning_store = learning_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_plan_get",
            description="Read a saved learning plan by learning_plan_id. Call learning_plan_list first if unsure.",
            parameters_schema={
                "type": "object",
                "properties": {"learning_plan_id": {"type": "string"}},
                "required": ["learning_plan_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("learning_plan_id"), field_name="learning_plan_id")
            record = self._learning_store.get_learning_plan(record_id)
            if record is None:
                return _not_found_result("learning_plan_get", "learning_plan", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_plan_get", "learning_plan", record.learning_plan_id, record)


class LearningPlanListTool:
    """List learning plans."""

    def __init__(self, learning_store: LearningStore) -> None:
        self._learning_store = learning_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_plan_list",
            description="List saved learning plans. Optional filter: target_application_id.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "include_archived": {"type": "boolean", "default": False},
                    "target_application_id": {"type": "string"},
                },
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._learning_store.list_learning_plans(
            include_archived=_optional_bool(args.get("include_archived")),
            target_application_id=_optional_prefixed_id(args.get("target_application_id"), "application"),
        )
        return _list_result("learning_plan_list", "learning_plan", records)


class LearningTaskCreateTool:
    """Create or reuse one learning task."""

    def __init__(self, learning_store: LearningStore, session_repository: SessionRepository) -> None:
        self._learning_store = learning_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_task_create",
            description=(
                "Create a concrete learning task under an optional learning plan. Use this for actionable daily or "
                "weekly tasks, not for long note bodies."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "learning_task_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "learning_plan_id": {"type": "string"},
                    "description": {"type": "string"},
                    "task_type": {
                        "type": "string",
                        "enum": [
                            "read_resource",
                            "practice_question",
                            "write_answer",
                            "revise_resume",
                            "mock_interview",
                            "review_note",
                            "custom",
                        ],
                    },
                    "priority": {"type": "string", "enum": ["high", "medium", "low"]},
                    "state": {"type": "string", "enum": ["todo", "doing", "blocked", "done", "skipped"]},
                    "skill_tags": {"type": "array", "items": {"type": "string"}},
                    "estimated_minutes": {"type": "integer"},
                    "planned_start_date": {"type": "string"},
                    "due_date": {"type": "string"},
                    "resource_refs": {"type": "array", "items": {"type": "string"}},
                    "question_refs": {"type": "array", "items": {"type": "string"}},
                    "note_refs": {"type": "array", "items": {"type": "string"}},
                    "output_artifact_id": {"type": "string"},
                    "success_criteria": {"type": "array", "items": {"type": "string"}},
                    "progress_notes": {"type": "string"},
                },
                "required": ["title", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _optional_prefixed_id(args.get("learning_task_id"), "learning_task") or _new_id(
                "learning_task"
            )
            existing = self._learning_store.get_learning_task(record_id)
            if existing is not None:
                return _record_result(
                    "learning_task_create",
                    "learning_task",
                    existing.learning_task_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = LearningTask(
                learning_task_id=record_id,
                status=LearningRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=_optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    args.get("source_artifact_id"),
                    field_name="source_artifact_id",
                ),
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
                created_at=_now(),
                updated_at=_now(),
                title=_required_string(args.get("title"), field_name="title"),
                learning_plan_id=_optional_prefixed_id(args.get("learning_plan_id"), "learning_plan"),
                description=_optional_string(args.get("description")) or "",
                task_type=_optional_string(args.get("task_type")) or "custom",
                priority=_optional_string(args.get("priority")) or "medium",
                state=_optional_string(args.get("state")) or "todo",
                skill_tags=_optional_string_list(args.get("skill_tags"), field_name="skill_tags"),
                estimated_minutes=_optional_int(args.get("estimated_minutes"), field_name="estimated_minutes"),
                planned_start_date=_optional_datetime(args.get("planned_start_date"), field_name="planned_start_date"),
                due_date=_optional_datetime(args.get("due_date"), field_name="due_date"),
                resource_refs=_optional_resource_refs(args.get("resource_refs")),
                question_refs=_optional_prefixed_id_list(args.get("question_refs"), "question", field_name="question_refs"),
                note_refs=_optional_prefixed_id_list(args.get("note_refs"), "note", field_name="note_refs"),
                output_artifact_id=_optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    args.get("output_artifact_id"),
                    field_name="output_artifact_id",
                ),
                success_criteria=_optional_string_list(args.get("success_criteria"), field_name="success_criteria"),
                progress_notes=_optional_string(args.get("progress_notes")) or "",
            )
            saved = self._learning_store.save_learning_task(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_task_create", "learning_task", saved.learning_task_id, saved)


class LearningTaskGetTool:
    """Read one learning task."""

    def __init__(self, learning_store: LearningStore) -> None:
        self._learning_store = learning_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_task_get",
            description="Read a saved learning task by learning_task_id. Call learning_task_list first if unsure.",
            parameters_schema={
                "type": "object",
                "properties": {"learning_task_id": {"type": "string"}},
                "required": ["learning_task_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _required_string(args.get("learning_task_id"), field_name="learning_task_id")
            record = self._learning_store.get_learning_task(record_id)
            if record is None:
                return _not_found_result("learning_task_get", "learning_task", record_id)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_task_get", "learning_task", record.learning_task_id, record)


class LearningTaskListTool:
    """List learning tasks."""

    def __init__(self, learning_store: LearningStore) -> None:
        self._learning_store = learning_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_task_list",
            description="List saved learning tasks. Optional filters: learning_plan_id and state.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "include_archived": {"type": "boolean", "default": False},
                    "learning_plan_id": {"type": "string"},
                    "state": {"type": "string"},
                },
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        args = _require_arguments(arguments)
        records = self._learning_store.list_learning_tasks(
            include_archived=_optional_bool(args.get("include_archived")),
            learning_plan_id=_optional_prefixed_id(args.get("learning_plan_id"), "learning_plan"),
            state=_optional_string(args.get("state")),
        )
        return _list_result("learning_task_list", "learning_task", records)


class LearningTaskUpdateStateTool:
    """Update the execution state of one learning task."""

    def __init__(self, learning_store: LearningStore) -> None:
        self._learning_store = learning_store

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_task_update_state",
            description=(
                "Update a learning task state after the user reports progress or completion. If state is done, "
                "the store sets completed_at when omitted."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "learning_task_id": {"type": "string"},
                    "state": {"type": "string", "enum": ["todo", "doing", "blocked", "done", "skipped"]},
                    "completed_at": {"type": "string"},
                },
                "required": ["learning_task_id", "state"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        _ = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record = self._learning_store.update_task_state(
                _required_string(args.get("learning_task_id"), field_name="learning_task_id"),
                state=_required_string(args.get("state"), field_name="state"),
                completed_at=_optional_datetime(args.get("completed_at"), field_name="completed_at"),
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_task_update_state", "learning_task", record.learning_task_id, record)


class LearningCheckinCreateTool:
    """Create one progress checkin."""

    def __init__(self, learning_store: LearningStore, session_repository: SessionRepository) -> None:
        self._learning_store = learning_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_checkin_create",
            description=(
                "Create one learning progress checkin when the user reports progress, blockers, confidence, "
                "or next action. Long reflections should go to NoteService separately only when requested."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "checkin_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "learning_plan_id": {"type": "string"},
                    "learning_task_id": {"type": "string"},
                    "checkin_date": {"type": "string"},
                    "minutes_spent": {"type": "integer"},
                    "progress_state": {
                        "type": "string",
                        "enum": ["not_started", "in_progress", "completed", "blocked", "skipped"],
                    },
                    "summary": {"type": "string"},
                    "blockers": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "next_action": {"type": "string"},
                    "note_refs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments, allowed_fields=_CHECKIN_CREATE_FIELDS)
            record = ProgressCheckin(
                checkin_id=_optional_prefixed_id(args.get("checkin_id"), "checkin") or _new_id("checkin"),
                status=LearningRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=_optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    args.get("source_artifact_id"),
                    field_name="source_artifact_id",
                ),
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
                created_at=_now(),
                updated_at=_now(),
                learning_plan_id=_optional_prefixed_id(args.get("learning_plan_id"), "learning_plan"),
                learning_task_id=_optional_prefixed_id(args.get("learning_task_id"), "learning_task"),
                checkin_date=_optional_datetime(args.get("checkin_date"), field_name="checkin_date"),
                minutes_spent=_optional_int(args.get("minutes_spent"), field_name="minutes_spent"),
                progress_state=_optional_string(args.get("progress_state")) or "in_progress",
                summary=_optional_string(args.get("summary")) or "",
                blockers=_optional_string_list(args.get("blockers"), field_name="blockers"),
                confidence=_optional_string(args.get("confidence")) or "medium",
                next_action=_optional_string(args.get("next_action")) or "",
                note_refs=_optional_prefixed_id_list(args.get("note_refs"), "note", field_name="note_refs"),
            )
            saved = self._learning_store.append_progress_checkin(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_checkin_create", "checkin", saved.checkin_id, saved)


class LearningWeaknessCreateTool:
    """Create or reuse one tracked learning weakness."""

    def __init__(self, learning_store: LearningStore, session_repository: SessionRepository) -> None:
        self._learning_store = learning_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_weakness_create",
            description="Create a tracked weakness from a fit report, interview review, note, or user-stated gap.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "weakness_id": {"type": "string"},
                    "source_artifact_id": {"type": "string"},
                    "evidence_refs": {"type": "array", "items": {"type": "string"}},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "weakness_type": {
                        "type": "string",
                        "enum": ["skill_gap", "project_gap", "interview_gap", "resume_gap", "habit", "confidence", "other"],
                    },
                    "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    "state": {"type": "string", "enum": ["open", "improving", "resolved", "ignored"]},
                    "skill_tags": {"type": "array", "items": {"type": "string"}},
                    "target_application_ids": {"type": "array", "items": {"type": "string"}},
                    "source_report_ids": {"type": "array", "items": {"type": "string"}},
                    "related_task_ids": {"type": "array", "items": {"type": "string"}},
                    "related_note_ids": {"type": "array", "items": {"type": "string"}},
                    "last_observed_at": {"type": "string"},
                    "resolved_at": {"type": "string"},
                    "resolution_summary": {"type": "string"},
                },
                "required": ["title", "evidence_refs"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            record_id = _optional_prefixed_id(args.get("weakness_id"), "weakness") or _new_id("weakness")
            existing = self._learning_store.get_weakness_tracker(record_id)
            if existing is not None:
                return _record_result(
                    "learning_weakness_create",
                    "weakness",
                    existing.weakness_id,
                    existing,
                    extra={"idempotent_reused": True},
                )
            record = WeaknessTracker(
                weakness_id=record_id,
                status=LearningRecordStatus.ACTIVE,
                source_session_id=run_context.session_id,
                source_artifact_id=_optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    args.get("source_artifact_id"),
                    field_name="source_artifact_id",
                ),
                evidence_refs=_required_evidence_refs(args.get("evidence_refs")),
                created_at=_now(),
                updated_at=_now(),
                title=_required_string(args.get("title"), field_name="title"),
                description=_optional_string(args.get("description")) or "",
                weakness_type=_optional_string(args.get("weakness_type")) or "other",
                severity=_optional_string(args.get("severity")) or "medium",
                state=_optional_string(args.get("state")) or "open",
                skill_tags=_optional_string_list(args.get("skill_tags"), field_name="skill_tags"),
                target_application_ids=_optional_prefixed_id_list(
                    args.get("target_application_ids"),
                    "application",
                    field_name="target_application_ids",
                ),
                source_report_ids=_optional_string_list(args.get("source_report_ids"), field_name="source_report_ids"),
                related_task_ids=_optional_prefixed_id_list(
                    args.get("related_task_ids"),
                    "learning_task",
                    field_name="related_task_ids",
                ),
                related_note_ids=_optional_prefixed_id_list(args.get("related_note_ids"), "note", field_name="related_note_ids"),
                last_observed_at=_optional_datetime(args.get("last_observed_at"), field_name="last_observed_at"),
                resolved_at=_optional_datetime(args.get("resolved_at"), field_name="resolved_at"),
                resolution_summary=_optional_string(args.get("resolution_summary")) or "",
            )
            saved = self._learning_store.save_weakness_tracker(record)
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_weakness_create", "weakness", saved.weakness_id, saved)


class LearningWeaknessUpdateTool:
    """Update editable fields on one tracked weakness."""

    def __init__(self, learning_store: LearningStore, session_repository: SessionRepository) -> None:
        self._learning_store = learning_store
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="learning_weakness_update",
            description="Update a tracked weakness state, severity, related tasks, evidence, or resolution summary.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "weakness_id": {"type": "string"},
                    "updates": {"type": "object"},
                },
                "required": ["weakness_id", "updates"],
            },
        )

    def execute(self, arguments: dict[str, Any], context: RunContext) -> ToolExecutionResult:
        run_context = validate_context(context)
        try:
            args = _require_arguments(arguments)
            updates = _learning_update_payload(args.get("updates"), allowed_fields=_WEAKNESS_UPDATE_FIELDS)
            raw_source_artifact_id = updates.get("source_artifact_id")
            if raw_source_artifact_id is not None:
                updates["source_artifact_id"] = _optional_current_artifact(
                    self._session_repository,
                    run_context.session_id,
                    raw_source_artifact_id,
                    field_name="source_artifact_id",
                )
            if "target_application_ids" in updates:
                updates["target_application_ids"] = _optional_prefixed_id_list(
                    updates["target_application_ids"],
                    "application",
                    field_name="target_application_ids",
                )
            if "related_task_ids" in updates:
                updates["related_task_ids"] = _optional_prefixed_id_list(
                    updates["related_task_ids"],
                    "learning_task",
                    field_name="related_task_ids",
                )
            if "related_note_ids" in updates:
                updates["related_note_ids"] = _optional_prefixed_id_list(
                    updates["related_note_ids"],
                    "note",
                    field_name="related_note_ids",
                )
            record = self._learning_store.update_weakness_tracker(
                _required_string(args.get("weakness_id"), field_name="weakness_id"),
                updates=updates,
            )
        except (StorageError, ValidationError) as exc:
            raise ToolExecutionError(str(exc)) from exc
        return _record_result("learning_weakness_update", "weakness", record.weakness_id, record)


def _require_arguments(arguments: dict[str, Any], *, allowed_fields: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    path_fields = {"path", "file_path", "workspace_path", "absolute_path", "relative_path"}
    store_owned_fields = {"created_at", "updated_at", "source_session_id", "status"}
    for key in arguments:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError("Tool argument keys must be non-empty strings.")
        normalized_key = key.strip()
        if normalized_key in path_fields:
            raise ToolExecutionError(f"Path arguments are not allowed: {key}")
        if normalized_key in store_owned_fields:
            raise ToolExecutionError(f"Store-owned fields are not accepted: {key}")
        if allowed_fields is not None and normalized_key not in allowed_fields:
            allowed_text = ", ".join(sorted(allowed_fields))
            raise ToolExecutionError(f"Unsupported argument field: {key}. Allowed fields: {allowed_text}")
    return arguments


def _optional_current_artifact(
    session_repository: SessionRepository,
    session_id: str,
    raw: Any,
    *,
    field_name: str,
) -> str | None:
    artifact_id = _optional_string(raw)
    if artifact_id is None:
        return None
    try:
        artifact = require_session_artifact(session_repository, session_id, artifact_id)
    except ToolExecutionError as exc:
        raise ToolExecutionError(f"{field_name} must reference a current session artifact: {artifact_id}") from exc
    return artifact.artifact_id


def _required_string(raw: Any, *, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be a non-empty string.")
    return raw.strip()


def _optional_string(raw: Any) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ToolExecutionError("optional string argument must be a string.")
    normalized = raw.strip()
    return normalized or None


def _optional_prefixed_id(raw: Any, prefix: str) -> str | None:
    value = _optional_string(raw)
    if value is None:
        return None
    marker = f"{prefix}_"
    stem = value[len(marker):] if value.startswith(marker) else value
    slug = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    if not slug:
        return None
    return f"{marker}{slug[:100]}"


def _optional_prefixed_id_list(raw: Any, prefix: str, *, field_name: str) -> list[str]:
    values = _optional_string_list(raw, field_name=field_name)
    output: list[str] = []
    for item in values:
        normalized = _optional_prefixed_id(item, prefix)
        if normalized is None:
            continue
        output.append(normalized)
    return output


def _optional_string_list(raw: Any, *, field_name: str) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    if not isinstance(raw, list):
        raise ToolExecutionError(f"'{field_name}' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ToolExecutionError(f"each '{field_name}' item must be a non-empty string.")
        output.append(item.strip())
    return output


def _required_evidence_refs(raw: Any) -> list[str]:
    refs = _optional_evidence_ref_list(raw)
    if not refs:
        raise ToolExecutionError("'evidence_refs' must include at least one reference.")
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        normalized = _normalize_evidence_ref(ref)
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output


def _optional_evidence_ref_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        return [stripped] if stripped else []
    if not isinstance(raw, list):
        raise ToolExecutionError("'evidence_refs' must be a list of strings.")
    output: list[str] = []
    for item in raw:
        if isinstance(item, str):
            stripped = item.strip()
            if stripped:
                output.append(stripped)
            continue
        raise ToolExecutionError("each 'evidence_refs' item must be a string.")
    return output


def _normalize_evidence_ref(raw: str) -> str:
    value = raw.strip().strip("`")
    if ":" not in value:
        return value
    raw_kind, raw_id = value.split(":", 1)
    kind = _EVIDENCE_REF_TYPE_ALIASES.get(raw_kind.strip().lower())
    record_id = raw_id.strip().strip("`")
    if kind is None or not record_id:
        return value
    if kind == "application" and record_id.startswith("application_"):
        return record_id
    if kind == "artifact" and record_id.startswith("artifact_"):
        return record_id
    if kind == "career_profile" and record_id.startswith("career_profile_"):
        return record_id
    if kind == "checkin" and record_id.startswith("checkin_"):
        return record_id
    if kind == "company" and record_id.startswith("company_"):
        return record_id
    if kind == "experience" and record_id.startswith("experience_"):
        return record_id
    if kind == "fit" and record_id.startswith("fit_"):
        return record_id
    if kind == "jd" and (record_id.startswith("jd_") or record_id.startswith("jd_analysis_")):
        return record_id
    if kind == "learning_plan" and record_id.startswith("learning_plan_"):
        return record_id
    if kind == "learning_task" and record_id.startswith("learning_task_"):
        return record_id
    if kind == "note" and record_id.startswith("note_"):
        return record_id
    if kind == "question" and record_id.startswith("question_"):
        return record_id
    if kind == "resource" and record_id.startswith("resource_"):
        return record_id
    if kind == "resume_profile" and record_id.startswith("resume_profile_"):
        return record_id
    if kind == "resume_version" and record_id.startswith("resume_version_"):
        return record_id
    if kind == "review" and record_id.startswith("review_"):
        return record_id
    if kind == "sess" and record_id.startswith("sess_"):
        return record_id
    if kind == "skill_req" and record_id.startswith("skill_req_"):
        return record_id
    if kind == "weakness" and record_id.startswith("weakness_"):
        return record_id
    return value


def _optional_resource_refs(raw: Any) -> list[str]:
    refs = _optional_string_list(raw, field_name="resource_refs")
    output: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        if not _RESOURCE_REF_RE.fullmatch(ref):
            continue
        if ref in seen:
            continue
        output.append(ref)
        seen.add(ref)
    return output


def _optional_datetime(raw: Any, *, field_name: str) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError(f"'{field_name}' must be an ISO datetime string.")
    normalized = raw.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ToolExecutionError(f"'{field_name}' must be an ISO datetime string.") from exc


def _optional_int(raw: Any, *, field_name: str) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ToolExecutionError(f"'{field_name}' must be an integer.")
    return int(raw)


def _optional_bool(raw: Any) -> bool:
    if raw is None:
        return False
    if not isinstance(raw, bool):
        raise ToolExecutionError("'include_archived' must be a boolean.")
    return raw


def _learning_update_payload(raw: Any, *, allowed_fields: set[str]) -> dict[str, Any]:
    payload = _required_dict(raw, field_name="updates")
    _reject_unsupported_fields(payload, allowed_fields, payload_name="updates")
    for list_field in (
        "evidence_refs",
        "focus_skill_tags",
        "goals",
        "resource_refs",
        "question_refs",
        "note_refs",
        "skill_tags",
        "success_criteria",
        "source_report_ids",
    ):
        if list_field in payload:
            payload[list_field] = (
                _optional_resource_refs(payload[list_field])
                if list_field == "resource_refs"
                else _optional_string_list(payload[list_field], field_name=list_field)
            )
    for datetime_field in (
        "completed_at",
        "due_date",
        "end_date",
        "last_observed_at",
        "planned_start_date",
        "resolved_at",
        "start_date",
    ):
        if datetime_field in payload:
            payload[datetime_field] = _optional_datetime(payload[datetime_field], field_name=datetime_field)
    if "estimated_minutes" in payload:
        payload["estimated_minutes"] = _optional_int(payload["estimated_minutes"], field_name="estimated_minutes")
    return payload


def _required_dict(raw: Any, *, field_name: str) -> dict[str, Any]:
    if isinstance(raw, str):
        raw = _json_object_or_array(raw, field_name=field_name)
    if not isinstance(raw, dict):
        raise ToolExecutionError(f"'{field_name}' must be an object.")
    return dict(raw)


def _json_object_or_array(raw: str, *, field_name: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"'{field_name}' must be valid JSON.") from exc


def _reject_unsupported_fields(payload: dict[str, Any], allowed: set[str], *, payload_name: str) -> None:
    for key in payload:
        if not isinstance(key, str) or not key.strip():
            raise ToolExecutionError(f"'{payload_name}' keys must be non-empty strings.")
        if key.strip() not in allowed:
            allowed_text = ", ".join(sorted(allowed))
            raise ToolExecutionError(f"Unsupported {payload_name} field: {key}. Allowed fields: {allowed_text}")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _now() -> datetime:
    return app_now()


def _record_result(
    tool_name: str,
    record_type: str,
    record_id: str,
    record: LearningPlan | LearningTask | ProgressCheckin | WeaknessTracker,
    *,
    extra: dict[str, Any] | None = None,
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": True,
        "status": _enum_value(record.status),
        "source_session_id": record.source_session_id,
        "source_artifact_id": record.source_artifact_id,
        "evidence_refs": record.evidence_refs,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "record": _record_to_payload(record),
    }
    if extra:
        payload.update(extra)
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _not_found_result(tool_name: str, record_type: str, record_id: str) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": False,
        "message": f"{record_type} not found: {record_id}",
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _list_result(
    tool_name: str,
    record_type: str,
    records: list[LearningPlan] | list[LearningTask],
) -> ToolExecutionResult:
    payload = {
        "record_type": record_type,
        "records": [_record_to_payload(record) for record in records],
    }
    return ToolExecutionResult(tool_name=tool_name, success=True, content=json.dumps(payload, ensure_ascii=False))


def _record_to_payload(record: LearningPlan | LearningTask | ProgressCheckin | WeaknessTracker) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": _enum_value(record.status),
        "source_session_id": record.source_session_id,
        "source_artifact_id": record.source_artifact_id,
        "evidence_refs": record.evidence_refs,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
    }
    if isinstance(record, LearningPlan):
        base.update(
            {
                "learning_plan_id": record.learning_plan_id,
                "title": record.title,
                "description": record.description,
                "plan_type": _enum_value(record.plan_type),
                "target_application_id": record.target_application_id,
                "target_role": record.target_role,
                "target_company": record.target_company,
                "start_date": _optional_to_iso(record.start_date),
                "end_date": _optional_to_iso(record.end_date),
                "priority": _enum_value(record.priority),
                "goals": record.goals,
                "focus_skill_tags": record.focus_skill_tags,
                "task_ids": record.task_ids,
                "weakness_ids": record.weakness_ids,
                "review_schedule_ids": record.review_schedule_ids,
                "progress_summary": record.progress_summary,
            }
        )
        return base
    if isinstance(record, LearningTask):
        base.update(
            {
                "learning_task_id": record.learning_task_id,
                "title": record.title,
                "learning_plan_id": record.learning_plan_id,
                "description": record.description,
                "task_type": _enum_value(record.task_type),
                "priority": _enum_value(record.priority),
                "state": _enum_value(record.state),
                "skill_tags": record.skill_tags,
                "estimated_minutes": record.estimated_minutes,
                "planned_start_date": _optional_to_iso(record.planned_start_date),
                "due_date": _optional_to_iso(record.due_date),
                "completed_at": _optional_to_iso(record.completed_at),
                "resource_refs": record.resource_refs,
                "question_refs": record.question_refs,
                "note_refs": record.note_refs,
                "output_artifact_id": record.output_artifact_id,
                "success_criteria": record.success_criteria,
                "progress_notes": record.progress_notes,
            }
        )
        return base
    if isinstance(record, ProgressCheckin):
        base.update(
            {
                "checkin_id": record.checkin_id,
                "learning_plan_id": record.learning_plan_id,
                "learning_task_id": record.learning_task_id,
                "checkin_date": _optional_to_iso(record.checkin_date),
                "minutes_spent": record.minutes_spent,
                "progress_state": _enum_value(record.progress_state),
                "summary": record.summary,
                "blockers": record.blockers,
                "confidence": _enum_value(record.confidence),
                "next_action": record.next_action,
                "note_refs": record.note_refs,
            }
        )
        return base
    base.update(
        {
            "weakness_id": record.weakness_id,
            "title": record.title,
            "description": record.description,
            "weakness_type": _enum_value(record.weakness_type),
            "severity": _enum_value(record.severity),
            "state": _enum_value(record.state),
            "skill_tags": record.skill_tags,
            "target_application_ids": record.target_application_ids,
            "source_report_ids": record.source_report_ids,
            "related_task_ids": record.related_task_ids,
            "related_note_ids": record.related_note_ids,
            "last_observed_at": _optional_to_iso(record.last_observed_at),
            "resolved_at": _optional_to_iso(record.resolved_at),
            "resolution_summary": record.resolution_summary,
        }
    )
    return base


def _enum_value(value: Enum | str) -> str:
    if isinstance(value, str):
        return value
    return str(value.value)


def _to_iso(value: datetime) -> str:
    return to_app_iso(value)


def _optional_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _to_iso(value)
