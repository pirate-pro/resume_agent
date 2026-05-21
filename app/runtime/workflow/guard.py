"""Deterministic workflow guard for career tool execution."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime
from enum import Enum
from typing import Any, Callable, cast

from app.career.models import CareerRecordStatus
from app.career.store import CareerProductStore
from app.core.errors import SessionNotFoundError, StorageError, ValidationError
from app.domain.models import RunContext, ToolCall, ToolExecutionResult
from app.domain.protocols import SessionRepository

__all__ = ["WorkflowGuardDecision", "WorkflowRuntimeGuard"]

_MAIN_STAGE_FINAL_BLOCK_TOOLS = {
    "tool_search",
    "delegate_agents",
    "agent_task_status",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_read_artifact",
    "session_search_artifact",
    "session_create_text_artifact",
    "career_resume_profile_get",
    "career_resume_profile_list",
    "career_resume_profile_save",
    "career_profile_get",
    "career_profile_merge",
    "career_jd_analysis_get",
    "career_jd_analysis_list",
    "career_jd_analysis_save",
    "career_job_fit_report_get",
    "career_job_fit_report_list",
    "career_job_fit_report_save",
    "career_application_get",
    "career_application_list",
    "career_application_create",
    "career_application_merge",
    "career_resume_version_get",
    "career_resume_version_list",
    "career_resume_version_create",
}
_MAIN_JD_FIT_PARTIAL_BLOCK_TOOLS = {
    "delegate_agents",
    "agent_task_status",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_read_artifact",
    "session_search_artifact",
    "session_create_text_artifact",
    "career_resume_profile_get",
    "career_profile_get",
    "career_jd_analysis_get",
    "career_jd_analysis_save",
    "career_job_fit_report_get",
    "career_job_fit_report_save",
}
_MAIN_RESUME_VERSION_PARTIAL_BLOCK_TOOLS = {
    "delegate_agents",
    "agent_task_status",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_read_artifact",
    "session_search_artifact",
    "session_create_text_artifact",
    "career_resume_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_resume_version_get",
    "career_resume_version_create",
}
_MAIN_RESUME_DIAGNOSIS_PARTIAL_BLOCK_TOOLS = {
    "delegate_agents",
    "agent_task_status",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_read_artifact",
    "session_search_artifact",
    "session_create_text_artifact",
    "career_resume_profile_save",
}
_MAIN_RESUME_DIAGNOSIS_FINAL_BLOCK_TOOLS = _MAIN_STAGE_FINAL_BLOCK_TOOLS - {
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_application_get",
    "career_resume_version_get",
}
_PRODUCT_GET_ID_FIELDS = {
    "career_resume_profile_get": ("resume_profile", "resume_profile_id"),
    "career_profile_get": ("career_profile", "career_profile_id"),
    "career_jd_analysis_get": ("jd_analysis", "jd_analysis_id"),
    "career_job_fit_report_get": ("job_fit_report", "job_fit_report_id"),
    "career_application_get": ("career_application", "application_id"),
    "career_resume_version_get": ("resume_version", "resume_version_id"),
}
_CAREER_PROFILE_ALLOWED_UPDATE_FIELDS = {
    "career_goal",
    "target_roles",
    "preferred_industries",
    "preferred_cities",
    "strengths",
    "weaknesses",
    "skills",
    "interests",
    "education_summary",
    "experience_summary",
    "resume_issues",
    "interview_weaknesses",
}
_CAREER_PROFILE_UPDATE_ALIASES = {
    "target_direction": "career_goal",
    "target_position": "target_roles",
    "target_role": "target_roles",
    "core_skills": "skills",
    "key_skills": "skills",
    "resume_optimization_priority": "resume_issues",
}
_CAREER_PROFILE_IGNORED_UPDATE_FIELDS = {
    "education",
    "job_market_fit",
    "key_project",
    "name",
    "resume_profile_id",
    "summary",
    "work_experience_years",
}
_CHILD_JOB_FIT_LOW_LEVEL_TOOLS = [
    "session_read_artifact",
    "session_list_artifacts",
    "career_resume_profile_get",
    "career_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
]


@dataclass(frozen=True, slots=True)
class WorkflowGuardDecision:
    """Decision returned before a tool executes."""

    tool_call: ToolCall
    result: ToolExecutionResult | None = None
    event_payload: dict[str, Any] | None = None


class WorkflowRuntimeGuard:
    """Apply career workflow stage locks before tool execution."""

    def __init__(self, *, career_store: CareerProductStore, session_repository: SessionRepository) -> None:
        self._career_store = career_store
        self._session_repository = session_repository

    def inspect(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        if not isinstance(tool_call, ToolCall):
            raise ValidationError("tool_call must be ToolCall.")
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        main_stage_decision = self._inspect_main_stage_gate(tool_call, context)
        if main_stage_decision is not None:
            return main_stage_decision
        handlers: dict[str, Callable[[ToolCall, RunContext], WorkflowGuardDecision]] = {
            "delegate_agents": self._inspect_delegate_agents,
            "session_list_artifacts": self._inspect_child_low_level_action,
            "session_read_artifact": self._inspect_child_low_level_action,
            "session_create_text_artifact": self._inspect_session_create_text_artifact,
            "career_jd_analysis_get": self._inspect_product_get,
            "career_job_fit_report_get": self._inspect_product_get,
            "career_resume_profile_get": self._inspect_product_get,
            "career_profile_get": self._inspect_product_get,
            "career_profile_merge": self._inspect_career_profile_merge,
            "career_application_get": self._inspect_product_get,
            "career_resume_version_get": self._inspect_product_get,
            "career_resume_profile_save": self._inspect_resume_profile_save,
            "career_jd_analysis_save": self._inspect_jd_analysis_save,
            "career_job_fit_report_save": self._inspect_job_fit_report_save,
            "career_application_create": self._inspect_application_create,
            "career_application_merge": self._inspect_application_merge,
            "career_resume_version_create": self._inspect_resume_version_create,
        }
        handler = handlers.get(tool_call.name)
        if handler is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        try:
            return handler(tool_call, context)
        except (StorageError, ValidationError):
            return WorkflowGuardDecision(tool_call=tool_call)

    def _inspect_product_get(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        if tool_call.name in {
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_resume_profile_get",
            "career_profile_get",
        }:
            child_decision = self._inspect_child_job_fit_low_level_action(tool_call, context)
            if child_decision.result is not None or child_decision.event_payload is not None:
                return child_decision
        duplicate_decision = self._reuse_duplicate_product_get(tool_call, context)
        if duplicate_decision is not None:
            return duplicate_decision
        return WorkflowGuardDecision(tool_call=tool_call)

    def _reuse_duplicate_product_get(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision | None:
        record_info = _PRODUCT_GET_ID_FIELDS.get(tool_call.name)
        if record_info is None:
            return None
        record_type, id_field = record_info
        requested_id = _string_or_none(_copy_arguments(tool_call.arguments).get(id_field))
        if requested_id is None:
            return None
        previous_payload = self._latest_successful_product_get_payload(
            context,
            tool_name=tool_call.name,
            id_field=id_field,
            requested_id=requested_id,
        )
        if previous_payload is None:
            return None
        ids = _payload_ids(previous_payload)
        ids.setdefault(id_field, requested_id)
        payload = {
            "workflow_runtime_result": True,
            "policy": "reuse",
            "idempotent_reused": True,
            "tool": tool_call.name,
            "reason": "product_record_already_read_in_run",
            "record_type": record_type,
            "record_id": requested_id,
            "ids": ids,
            "message": "同一 run 内已读取过该产品记录；复用当前工具状态中的记录摘要，不再重复展开完整记录。",
            "next_action": "直接使用已确认的 id 和上一条工具状态继续下一步；不要为了同一记录继续 get/list。",
        }
        return WorkflowGuardDecision(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name=tool_call.name,
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            ),
            event_payload={
                "workflow_runtime_result": True,
                "policy": "reuse",
                "tool_name": tool_call.name,
                "reason": "product_record_already_read_in_run",
                "record_type": record_type,
                "record_id": requested_id,
            },
        )

    def _latest_successful_product_get_payload(
        self,
        context: RunContext,
        *,
        tool_name: str,
        id_field: str,
        requested_id: str,
    ) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            if event.payload.get("tool_name") != tool_name or event.payload.get("success") is not True:
                continue
            if _is_runtime_block_tool_result(event):
                continue
            payload = _loads_json_object(event.payload.get("content"))
            if payload is None:
                continue
            if _payload_record_id(payload, id_field) != requested_id:
                continue
            latest = payload
        return latest

    def _inspect_main_stage_gate(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision | None:
        if context.agent_id != context.entry_agent_id:
            return None
        user_message = self._latest_user_message(context)
        if not user_message:
            return None
        gate = self._main_stage_gate_for_message(context, user_message=user_message)
        if gate is None:
            return None
        blocked_tools = set(gate["blocked_tools"])
        if tool_call.name not in blocked_tools:
            return None
        return _block_decision(
            tool_call,
            tool_name=tool_call.name,
            reason=str(gate["reason"]),
            next_action=str(gate["next_action"]),
            missing_outputs=list(gate.get("missing_outputs", [])),
            lock_key=f"main_stage_gate:{context.run_id}:{gate['stage']}:{gate['status']}",
            extra_payload={
                "stage": gate["stage"],
                "stage_status": gate["status"],
                "terminal": gate["status"] == "completed",
                "completed_refs": gate.get("completed_refs", {}),
                "next_allowed_tools": list(gate.get("next_allowed_tools", [])),
                "blocked_actions": sorted(blocked_tools),
            },
            extra_event_payload={
                "stage": gate["stage"],
                "stage_status": gate["status"],
                "terminal": gate["status"] == "completed",
                "next_allowed_tools": list(gate.get("next_allowed_tools", [])),
            },
        )

    def _main_stage_gate_for_message(self, context: RunContext, *, user_message: str) -> dict[str, Any] | None:
        if _is_resume_version_intent(user_message):
            if _allows_new_resume_version(user_message):
                return None
            return self._resume_version_stage_gate(context)
        if _is_jd_fit_only_intent(user_message):
            if _allows_reanalysis(user_message):
                return None
            return self._jd_fit_stage_gate(context)
        if _is_resume_diagnosis_intent(user_message):
            if _allows_reanalysis(user_message):
                return None
            return self._resume_diagnosis_stage_gate(context)
        return None

    def _jd_fit_stage_gate(self, context: RunContext) -> dict[str, Any] | None:
        if not self._current_run_has_any_successful_tool(
            context,
            {
                "delegate_agents",
                "career_jd_analysis_save",
                "career_job_fit_report_save",
                "career_application_create",
            },
        ):
            return None
        refs = self._current_jd_fit_refs(context)
        if refs is None:
            return None
        if refs.get("application_id"):
            return {
                "stage": "jd_fit",
                "status": "completed",
                "reason": "main_jd_fit_stage_complete_final_answer",
                "next_action": "JDAnalysis、JobFitReport 和 CareerApplication 已完成；不要继续读取、委派或重复保存，直接给用户最终答复。",
                "missing_outputs": [],
                "completed_refs": refs,
                "blocked_tools": _MAIN_STAGE_FINAL_BLOCK_TOOLS,
            }
        return {
            "stage": "jd_fit",
            "status": "fit_ready_application_missing",
            "reason": "main_jd_fit_records_ready_create_application",
            "next_action": "JDAnalysis 和 JobFitReport 已完成；不要重复委派或重新读取资料，下一步只需要调用 career_application_create 创建求职项目。",
            "missing_outputs": ["career_application"],
            "completed_refs": refs,
            "next_allowed_tools": ["career_application_create"],
            "blocked_tools": _MAIN_JD_FIT_PARTIAL_BLOCK_TOOLS,
        }

    def _resume_version_stage_gate(self, context: RunContext) -> dict[str, Any] | None:
        if not self._current_run_has_any_successful_tool(
            context,
            {
                "career_resume_version_create",
                "career_application_merge",
            },
        ):
            return None
        refs = self._current_resume_version_refs(context)
        if refs is None:
            return None
        if refs.get("application_merged") is True:
            return {
                "stage": "resume_version",
                "status": "completed",
                "reason": "main_resume_version_stage_complete_final_answer",
                "next_action": "ResumeVersion 已创建并已合并到 CareerApplication；不要继续读取或重复合并，直接给用户最终答复。",
                "missing_outputs": [],
                "completed_refs": refs,
                "blocked_tools": _MAIN_STAGE_FINAL_BLOCK_TOOLS,
            }
        return {
            "stage": "resume_version",
            "status": "version_ready_application_merge_missing",
            "reason": "main_resume_version_ready_merge_application",
            "next_action": "ResumeVersion 已创建；不要重复生成或读取全部关联记录，下一步只需要调用 career_application_merge 关联该版本。",
            "missing_outputs": ["career_application_merge"],
            "completed_refs": refs,
            "next_allowed_tools": ["career_application_merge"],
            "blocked_tools": _MAIN_RESUME_VERSION_PARTIAL_BLOCK_TOOLS,
        }

    def _resume_diagnosis_stage_gate(self, context: RunContext) -> dict[str, Any] | None:
        if not self._current_run_has_any_successful_tool(
            context,
            {
                "delegate_agents",
                "career_resume_profile_save",
                "career_profile_merge",
            },
        ):
            return None
        refs = self._current_resume_diagnosis_refs(context)
        if refs is None:
            return None
        if refs.get("career_profile_id"):
            return {
                "stage": "resume_diagnosis",
                "status": "completed",
                "reason": "main_resume_diagnosis_stage_complete_final_answer",
                "next_action": "ResumeProfile 和 CareerProfile 已完成；不要继续读取或重复委派，直接给用户最终答复。",
                "missing_outputs": [],
                "completed_refs": refs,
                "blocked_tools": _MAIN_RESUME_DIAGNOSIS_FINAL_BLOCK_TOOLS,
            }
        return {
            "stage": "resume_diagnosis",
            "status": "resume_profile_ready_career_profile_missing",
            "reason": "main_resume_profile_ready_merge_career_profile",
            "next_action": "ResumeProfile 已完成；不要重复委派或读取简历，下一步只需要调用 career_profile_merge 更新职业画像。",
            "missing_outputs": ["career_profile"],
            "completed_refs": refs,
            "next_allowed_tools": ["career_profile_merge"],
            "blocked_tools": _MAIN_RESUME_DIAGNOSIS_PARTIAL_BLOCK_TOOLS,
        }

    def _inspect_session_create_text_artifact(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        kind = _string_or_none(args.get("kind")) or "generated_file"
        if kind == "pasted_text" and context.agent_id != context.entry_agent_id:
            return self._block_child_pasted_text_artifact(tool_call, context)
        content = args.get("content")
        if isinstance(content, str) and content.strip():
            stage_output_decision = self._inspect_child_job_fit_stage_output_intent(tool_call, context, args)
            if stage_output_decision is not None:
                return stage_output_decision
            child_output_reuse = self._reuse_current_child_output_artifact_if_ready(tool_call, context, args)
            if child_output_reuse is not None:
                return child_output_reuse
            invalid_output_decision = self._inspect_child_output_artifact_content(tool_call, context, args)
            if invalid_output_decision is not None:
                return invalid_output_decision
            return WorkflowGuardDecision(tool_call=tool_call)
        empty_job_fit_decision = self._inspect_child_job_fit_empty_artifact_content(tool_call, context, args)
        if empty_job_fit_decision is not None:
            return empty_job_fit_decision
        recent_artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "title": artifact.title,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "status": artifact.status,
            }
            for artifact in self._session_repository.list_session_artifacts(context.session_id)[-5:]
        ]
        payload = {
            "workflow_runtime_result": True,
            "policy": "block",
            "skipped": True,
            "tool": "session_create_text_artifact",
            "reason": "empty_content",
            "message": "未创建 artifact：content 为空。不要重试空内容；如需文件，先生成正文，或复用 recent_artifacts 中已有 artifact。",
            "recent_artifacts": recent_artifacts,
        }
        return WorkflowGuardDecision(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name="session_create_text_artifact",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            ),
            event_payload={
                "workflow_runtime_result": True,
                "policy": "block",
                "tool_name": "session_create_text_artifact",
                "reason": "empty_content",
                "skipped": True,
                "recent_artifact_count": len(recent_artifacts),
            },
        )

    def _inspect_child_job_fit_empty_artifact_content(
        self,
        tool_call: ToolCall,
        context: RunContext,
        args: dict[str, Any],
    ) -> WorkflowGuardDecision | None:
        if context.agent_id != "job_agent" or context.agent_id == context.entry_agent_id:
            return None
        kind = _string_or_none(args.get("kind")) or "generated_file"
        if kind != "generated_file":
            return None
        output_kind = _child_output_kind(context.agent_id, _string_or_none(args.get("title")) or "")
        if output_kind != "job_fit_report" or not self._current_child_task_requires_job_fit_report(context):
            return None
        runtime_plan = self._child_job_fit_runtime_plan(
            context,
            missing_outputs=["job_fit_report_artifact", "job_fit_report"],
        )
        return _block_decision(
            tool_call,
            tool_name="session_create_text_artifact",
            reason="job_fit_report_artifact_missing_content",
            next_action=(
                "没有创建匹配报告 artifact：session_create_text_artifact 必须传完整 Markdown 到 content 字段，"
                "不要传 content_chars、content_omitted 或占位正文。直接重新调用 session_create_text_artifact，"
                "生成唯一的岗位匹配报告 artifact。"
            ),
            missing_outputs=["job_fit_report_artifact", "job_fit_report"],
            lock_key=f"child_job_fit_empty_artifact:{context.run_id}",
            extra_payload={
                **runtime_plan,
                "output_kind": output_kind,
                "blocked_actions": ["session_create_text_artifact"],
            },
            extra_event_payload={
                **runtime_plan,
                "output_kind": output_kind,
            },
        )

    def _inspect_child_job_fit_stage_output_intent(
        self,
        tool_call: ToolCall,
        context: RunContext,
        args: dict[str, Any],
    ) -> WorkflowGuardDecision | None:
        if context.agent_id != "job_agent" or context.agent_id == context.entry_agent_id:
            return None
        kind = _string_or_none(args.get("kind")) or "generated_file"
        if kind != "generated_file":
            return None
        output_kind = _child_output_kind(
            context.agent_id,
            " ".join(
                item
                for item in (
                    _string_or_none(args.get("title")),
                    _string_or_none(args.get("content")),
                )
                if item is not None
            ),
        )
        if output_kind != "jd_analysis_report":
            return None
        if not self._current_child_task_requires_job_fit_report(context):
            return None
        runtime_plan = self._child_job_fit_runtime_plan(
            context,
            missing_outputs=["job_fit_report_artifact", "job_fit_report"],
        )
        return _block_decision(
            tool_call,
            tool_name="session_create_text_artifact",
            reason="job_agent_should_not_create_separate_jd_analysis_artifact",
            next_action=(
                "JDAnalysis 只保存为产品记录，不要创建单独的 JD 分析 artifact。"
                "继续基于已读 JD、ResumeProfile 和 CareerProfile 生成唯一的岗位匹配报告 artifact，"
                "然后调用 career_job_fit_report_save，并把 report_artifact_id 指向该匹配报告 artifact。"
            ),
            missing_outputs=["job_fit_report_artifact", "job_fit_report"],
            lock_key=f"child_job_fit_single_report_artifact:{context.run_id}",
            extra_payload={
                **runtime_plan,
                "output_kind": output_kind,
                "blocked_actions": ["session_create_text_artifact"],
            },
            extra_event_payload={
                **runtime_plan,
                "output_kind": output_kind,
            },
        )

    def _reuse_current_child_output_artifact_if_ready(
        self,
        tool_call: ToolCall,
        context: RunContext,
        args: dict[str, Any],
    ) -> WorkflowGuardDecision | None:
        if context.agent_id == context.entry_agent_id:
            return None
        kind = _string_or_none(args.get("kind")) or "generated_file"
        if kind != "generated_file":
            return None
        output_kind = _child_output_kind(
            context.agent_id,
            " ".join(
                item
                for item in (
                    _string_or_none(args.get("title")),
                    _string_or_none(args.get("content")),
                )
                if item is not None
            ),
        )
        if output_kind is None:
            return None
        existing = self._latest_current_run_output_artifact(context, output_kind=output_kind)
        if existing is None:
            return None
        next_action = self._child_output_next_action(
            context,
            output_kind=output_kind,
            artifact_id=existing["artifact_id"],
        )
        missing_outputs = self._child_output_missing_outputs(context, output_kind=output_kind)
        runtime_plan = (
            self._child_job_fit_runtime_plan(
                context,
                missing_outputs=missing_outputs,
                report_artifact_id=existing["artifact_id"],
            )
            if output_kind == "job_fit_report"
            else {}
        )
        payload = {
            "workflow_runtime_result": True,
            "policy": "reuse",
            "tool": "session_create_text_artifact",
            "reason": "child_output_artifact_already_ready",
            "idempotent_reused": True,
            "artifact_id": existing["artifact_id"],
            "title": existing["title"],
            "kind": existing["kind"],
            "media_type": existing["media_type"],
            "output_kind": output_kind,
            "message": "当前子任务已创建对应输出 artifact，不要继续重写同一产物。",
            "next_action": next_action,
            "missing_outputs": missing_outputs,
            "blocked_actions": ["session_create_text_artifact"],
        }
        if output_kind == "job_fit_report":
            payload.update(runtime_plan)
        return WorkflowGuardDecision(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name="session_create_text_artifact",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            ),
            event_payload={
                "workflow_runtime_result": True,
                "policy": "reuse",
                "tool_name": "session_create_text_artifact",
                "reason": "child_output_artifact_already_ready",
                "artifact_id": existing["artifact_id"],
                "output_kind": output_kind,
                "missing_outputs": missing_outputs,
                **runtime_plan,
            },
        )

    def _inspect_child_output_artifact_content(
        self,
        tool_call: ToolCall,
        context: RunContext,
        args: dict[str, Any],
    ) -> WorkflowGuardDecision | None:
        if context.agent_id == context.entry_agent_id:
            return None
        kind = _string_or_none(args.get("kind")) or "generated_file"
        if kind != "generated_file":
            return None
        content = _string_or_none(args.get("content"))
        if content is None:
            return None
        output_kind = _child_output_kind(
            context.agent_id,
            " ".join(
                item
                for item in (
                    _string_or_none(args.get("title")),
                    content,
                )
                if item is not None
            ),
        )
        if output_kind != "job_fit_report":
            return None
        unsupported = self._unsupported_candidate_tech_claims(context, content)
        if not unsupported:
            return None
        supported_facts = self._supported_candidate_facts(context)
        runtime_plan = self._child_job_fit_runtime_plan(
            context,
            missing_outputs=["valid_job_fit_report_artifact"],
        )
        return _block_decision(
            tool_call,
            tool_name="session_create_text_artifact",
            reason="job_fit_report_artifact_candidate_facts_conflict",
            next_action=(
                "重新生成匹配报告正文：候选人事实必须以 ResumeProfile 和简历 artifact 为准；"
                "不要把 JD 要求或外部模板中的技术栈写成候选人已有经验。"
                "不要继续读取资料；直接基于 supported_candidate_facts 重写一个合法的匹配报告 artifact，"
                "并把完整 Markdown 放在 content 字段里，不要传 content_chars、content_omitted 或占位正文。"
            ),
            missing_outputs=["valid_job_fit_report_artifact"],
            lock_key=f"child_job_fit_invalid_artifact:{context.run_id}",
            extra_payload={
                **runtime_plan,
                "output_kind": output_kind,
                "unsupported_candidate_facts": unsupported[:10],
                "supported_candidate_facts": supported_facts,
                "blocked_actions": ["session_create_text_artifact"],
            },
            extra_event_payload={
                **runtime_plan,
                "output_kind": output_kind,
                "unsupported_candidate_fact_count": len(unsupported),
                "supported_candidate_facts": supported_facts,
            },
        )

    def _inspect_child_job_fit_low_level_action(
        self,
        tool_call: ToolCall,
        context: RunContext,
    ) -> WorkflowGuardDecision:
        if context.agent_id != "job_agent" or context.agent_id == context.entry_agent_id:
            return WorkflowGuardDecision(tool_call=tool_call)
        existing = self._latest_current_run_output_artifact(context, output_kind="job_fit_report")
        invalid_feedback = self._latest_child_output_invalid_feedback(context, output_kind="job_fit_report")
        if existing is None:
            if invalid_feedback is not None:
                runtime_plan = self._child_job_fit_runtime_plan(
                    context,
                    missing_outputs=["valid_job_fit_report_artifact"],
                )
                return _block_decision(
                    tool_call,
                    tool_name=tool_call.name,
                    reason="job_fit_report_invalid_artifact_retry_required",
                    next_action=(
                        "上一版匹配报告 artifact 因候选人事实冲突被拦截；不要继续读取或 get/list。"
                        "直接重新生成一个匹配报告 artifact，只把 JD 要求中的未覆盖内容写入差距/建议。"
                    ),
                    missing_outputs=["valid_job_fit_report_artifact"],
                    lock_key=f"child_job_fit_invalid_retry:{context.run_id}",
                    extra_payload={
                        **runtime_plan,
                        "output_kind": "job_fit_report",
                        "unsupported_candidate_facts": invalid_feedback.get("unsupported_candidate_facts", []),
                        "supported_candidate_facts": invalid_feedback.get("supported_candidate_facts", []),
                        "blocked_actions": [
                            "session_read_artifact",
                            "session_list_artifacts",
                            "career_resume_profile_get",
                            "career_profile_get",
                            "career_jd_analysis_get",
                            "career_job_fit_report_get",
                        ],
                    },
                    extra_event_payload={
                        **runtime_plan,
                        "output_kind": "job_fit_report",
                    },
                )
            return WorkflowGuardDecision(tool_call=tool_call)
        args = _copy_arguments(tool_call.arguments)
        if tool_call.name == "session_read_artifact":
            requested_artifact_id = _string_or_none(args.get("artifact_id"))
            if requested_artifact_id == existing["artifact_id"] and not self._current_run_has_successful_tool(
                context, "career_job_fit_report_save"
            ):
                return WorkflowGuardDecision(tool_call=tool_call)

        job_fit_saved = self._current_run_has_successful_tool(context, "career_job_fit_report_save")
        reason = (
            "job_fit_report_record_already_saved"
            if job_fit_saved
            else "job_fit_report_artifact_ready_stop_low_level_actions"
        )
        next_action = self._child_output_next_action(
            context,
            output_kind="job_fit_report",
            artifact_id=existing["artifact_id"],
        )
        missing_outputs = self._child_output_missing_outputs(context, output_kind="job_fit_report")
        runtime_plan = self._child_job_fit_runtime_plan(
            context,
            missing_outputs=missing_outputs,
            report_artifact_id=existing["artifact_id"],
        )
        return _block_decision(
            tool_call,
            tool_name=tool_call.name,
            reason=reason,
            next_action=next_action,
            missing_outputs=missing_outputs,
            lock_key=f"child_job_fit_stage:{context.run_id}:{existing['artifact_id']}",
            extra_payload={
                **runtime_plan,
                "output_kind": "job_fit_report",
                "report_artifact_id": existing["artifact_id"],
                "blocked_actions": [
                    "session_read_artifact",
                    "career_resume_profile_get",
                    "career_profile_get",
                    "session_create_text_artifact",
                ],
            },
            extra_event_payload={
                **runtime_plan,
                "output_kind": "job_fit_report",
                "report_artifact_id": existing["artifact_id"],
            },
        )

    def _inspect_child_low_level_action(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        job_fit_decision = self._inspect_child_job_fit_low_level_action(tool_call, context)
        if job_fit_decision.result is not None or job_fit_decision.event_payload is not None:
            return job_fit_decision
        return self._inspect_child_resume_low_level_action(tool_call, context)

    def _inspect_child_resume_low_level_action(
        self,
        tool_call: ToolCall,
        context: RunContext,
    ) -> WorkflowGuardDecision:
        if context.agent_id != "resume_agent" or context.agent_id == context.entry_agent_id:
            return WorkflowGuardDecision(tool_call=tool_call)
        existing = self._latest_current_run_output_artifact(context, output_kind="resume_diagnosis")
        if existing is None or not self._current_run_has_successful_tool(context, "career_resume_profile_save"):
            return WorkflowGuardDecision(tool_call=tool_call)
        return _block_decision(
            tool_call,
            tool_name=tool_call.name,
            reason="resume_profile_and_diagnosis_ready_stop_low_level_actions",
            next_action="ResumeProfile 和诊断 artifact 已完成；停止读取或重写资料，直接总结已保存的产品记录。",
            missing_outputs=[],
            lock_key=f"child_resume_diagnosis_stage:{context.run_id}:{existing['artifact_id']}",
            extra_payload={
                "output_kind": "resume_diagnosis",
                "diagnosis_artifact_id": existing["artifact_id"],
                "blocked_actions": ["session_read_artifact", "session_create_text_artifact"],
            },
            extra_event_payload={
                "output_kind": "resume_diagnosis",
                "diagnosis_artifact_id": existing["artifact_id"],
            },
        )

    def _child_output_next_action(self, context: RunContext, *, output_kind: str, artifact_id: str) -> str:
        if output_kind == "job_fit_report":
            if self._current_run_has_successful_tool(context, "career_job_fit_report_save"):
                return "JobFitReport 已保存；停止低层读取和重写，直接总结已保存的产品记录。"
            if self._current_run_has_successful_tool(context, "career_jd_analysis_save"):
                return f"调用 career_job_fit_report_save，并把 report_artifact_id 设置为已有 artifact_id：{artifact_id}。"
            return (
                "报告 artifact 已就绪；不要继续读取或重写资料。先调用 career_jd_analysis_save 保存 JDAnalysis，"
                f"再调用 career_job_fit_report_save，并把 report_artifact_id 设置为已有 artifact_id：{artifact_id}。"
            )
        return "调用 career_resume_profile_save，并把 diagnosis_artifact_id 设置为已有 artifact_id。"

    def _child_output_missing_outputs(self, context: RunContext, *, output_kind: str) -> list[str]:
        if output_kind != "job_fit_report":
            return ["resume_profile"] if not self._current_run_has_successful_tool(context, "career_resume_profile_save") else []
        if self._current_run_has_successful_tool(context, "career_job_fit_report_save"):
            return []
        missing: list[str] = []
        if not self._current_run_has_successful_tool(context, "career_jd_analysis_save"):
            missing.append("jd_analysis")
        if not self._current_run_has_successful_tool(context, "career_job_fit_report_save"):
            missing.append("job_fit_report")
        return missing

    def _child_job_fit_runtime_plan(
        self,
        context: RunContext,
        *,
        missing_outputs: list[str],
        report_artifact_id: str | None = None,
    ) -> dict[str, Any]:
        missing = {item for item in missing_outputs if isinstance(item, str)}
        if "valid_job_fit_report_artifact" in missing or "job_fit_report_artifact" in missing:
            return {
                "next_allowed_tools": ["session_create_text_artifact"],
                "required_tools": ["session_create_text_artifact"],
                "blocked_tools": _CHILD_JOB_FIT_LOW_LEVEL_TOOLS,
                "completed_refs": {},
            }
        if "jd_analysis" in missing:
            completed_refs = {}
            if report_artifact_id is not None:
                completed_refs["report_artifact_id"] = report_artifact_id
            return {
                "next_allowed_tools": ["career_jd_analysis_save"],
                "required_tools": ["career_jd_analysis_save"],
                "blocked_tools": [
                    *_CHILD_JOB_FIT_LOW_LEVEL_TOOLS,
                    "session_create_text_artifact",
                    "career_job_fit_report_save",
                ],
                "completed_refs": completed_refs,
            }
        if "job_fit_report" in missing:
            completed_refs = {}
            if report_artifact_id is not None:
                completed_refs["report_artifact_id"] = report_artifact_id
            return {
                "next_allowed_tools": ["career_job_fit_report_save"],
                "required_tools": ["career_job_fit_report_save"],
                "blocked_tools": [
                    *_CHILD_JOB_FIT_LOW_LEVEL_TOOLS,
                    "session_create_text_artifact",
                    "career_jd_analysis_save",
                ],
                "completed_refs": completed_refs,
            }
        return {
            "next_allowed_tools": [],
            "required_tools": [],
            "blocked_tools": [
                *_CHILD_JOB_FIT_LOW_LEVEL_TOOLS,
                "session_create_text_artifact",
                "career_jd_analysis_save",
                "career_job_fit_report_save",
            ],
            "completed_refs": {"report_artifact_id": report_artifact_id} if report_artifact_id is not None else {},
        }

    def _latest_current_run_output_artifact(self, context: RunContext, *, output_kind: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            if event.payload.get("tool_name") != "session_create_text_artifact" or event.payload.get("success") is not True:
                continue
            payload = _loads_json_object(event.payload.get("content"))
            if payload is None:
                continue
            artifact_id = _string_or_none(payload.get("artifact_id"))
            title = _string_or_none(payload.get("title")) or ""
            kind = _string_or_none(payload.get("kind")) or ""
            media_type = _string_or_none(payload.get("media_type")) or ""
            if artifact_id is None or kind != "generated_file":
                continue
            if _child_output_kind(context.agent_id, title) != output_kind:
                continue
            latest = {
                "artifact_id": artifact_id,
                "title": title,
                "kind": kind,
                "media_type": media_type,
            }
        return latest

    def _latest_child_output_invalid_feedback(self, context: RunContext, *, output_kind: str) -> dict[str, Any] | None:
        latest: dict[str, Any] | None = None
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            if event.payload.get("tool_name") != "session_create_text_artifact" or event.payload.get("success") is not True:
                continue
            payload = _loads_json_object(event.payload.get("content"))
            if payload is None:
                continue
            if payload.get("workflow_runtime_result") is not True or payload.get("policy") != "block":
                continue
            if payload.get("output_kind") != output_kind:
                continue
            if payload.get("reason") != "job_fit_report_artifact_candidate_facts_conflict":
                continue
            latest = payload
        return latest

    def _current_run_has_successful_tool(self, context: RunContext, tool_name: str) -> bool:
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            if _is_runtime_block_tool_result(event):
                continue
            if event.payload.get("tool_name") == tool_name and event.payload.get("success") is True:
                return True
        return False

    def _current_run_has_any_successful_tool(self, context: RunContext, tool_names: set[str]) -> bool:
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            if _is_runtime_block_tool_result(event):
                continue
            if event.payload.get("tool_name") in tool_names and event.payload.get("success") is True:
                return True
        return False

    def _current_child_task_requires_job_fit_report(self, context: RunContext) -> bool:
        if context.agent_id != "job_agent" or context.agent_id == context.entry_agent_id:
            return False
        texts: list[str] = []
        for event in self._session_repository.list_events(context.session_id):
            if event.type != "agent_task_assigned":
                continue
            payload = event.payload
            if not isinstance(payload, dict):
                continue
            if payload.get("target_agent_id") != context.agent_id:
                continue
            child_run_id = payload.get("child_run_id")
            if isinstance(child_run_id, str) and child_run_id and child_run_id != context.run_id:
                continue
            instruction = _string_or_none(payload.get("instruction"))
            if instruction is not None:
                texts.append(instruction)
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "user_message":
                continue
            content = _string_or_none(event.payload.get("content"))
            if content is not None:
                texts.append(content)
        return any(_task_requires_job_fit_report(text) for text in texts)

    def _current_jd_fit_refs(self, context: RunContext) -> dict[str, Any] | None:
        fit_report = _find_one(
            self._career_store.list_job_fit_reports(),
            lambda item: item.source_session_id == context.session_id and item.status == CareerRecordStatus.ACTIVE,
        )
        if fit_report is None:
            return None
        jd_analysis = _current_record_by_id(
            self._career_store.get_jd_analysis,
            fit_report.jd_analysis_id,
            context.session_id,
        )
        resume_profile = _current_record_by_id(
            self._career_store.get_resume_profile,
            fit_report.resume_profile_id,
            context.session_id,
        )
        application = _find_one(
            self._career_store.list_career_applications(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and (
                item.job_fit_report_id == fit_report.job_fit_report_id
                or (
                    item.jd_analysis_id == fit_report.jd_analysis_id
                    and item.resume_profile_id == fit_report.resume_profile_id
                )
            ),
        )
        refs: dict[str, Any] = {
            "job_fit_report_id": fit_report.job_fit_report_id,
            "jd_analysis_id": fit_report.jd_analysis_id,
            "resume_profile_id": fit_report.resume_profile_id,
            "report_artifact_id": fit_report.report_artifact_id,
            "source_artifact_id": fit_report.source_artifact_id,
        }
        if jd_analysis is not None:
            refs["jd_source_artifact_id"] = jd_analysis.source_artifact_id
        if resume_profile is not None:
            refs["resume_source_artifact_id"] = resume_profile.source_artifact_id
        if application is not None:
            refs["application_id"] = application.application_id
        return refs

    def _current_resume_version_refs(self, context: RunContext) -> dict[str, Any] | None:
        resume_version = _find_one(
            self._career_store.list_resume_versions(),
            lambda item: item.source_session_id == context.session_id and item.status == CareerRecordStatus.ACTIVE,
        )
        if resume_version is None:
            return None
        application = _find_one(
            self._career_store.list_career_applications(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and (
                resume_version.resume_version_id in item.resume_version_ids
                or (
                    item.jd_analysis_id == resume_version.target_jd_analysis_id
                    and item.resume_profile_id == resume_version.base_resume_profile_id
                )
            ),
        )
        refs: dict[str, Any] = {
            "resume_version_id": resume_version.resume_version_id,
            "artifact_id": resume_version.artifact_id,
            "base_resume_profile_id": resume_version.base_resume_profile_id,
            "target_jd_analysis_id": resume_version.target_jd_analysis_id,
        }
        if application is not None:
            refs["application_id"] = application.application_id
            refs["application_merged"] = resume_version.resume_version_id in application.resume_version_ids
        else:
            refs["application_merged"] = False
        return refs

    def _current_resume_diagnosis_refs(self, context: RunContext) -> dict[str, Any] | None:
        resume_profile = _find_one(
            self._career_store.list_resume_profiles(),
            lambda item: item.source_session_id == context.session_id and item.status == CareerRecordStatus.ACTIVE,
        )
        if resume_profile is None:
            return None
        career_profile = _find_one(
            self._career_store.list_career_profiles(),
            lambda item: item.source_session_id == context.session_id and item.status == CareerRecordStatus.ACTIVE,
        )
        refs: dict[str, Any] = {
            "resume_profile_id": resume_profile.resume_profile_id,
            "source_artifact_id": resume_profile.source_artifact_id,
            "diagnosis_artifact_id": resume_profile.diagnosis_artifact_id,
        }
        if career_profile is not None:
            refs["career_profile_id"] = career_profile.career_profile_id
        return refs

    def _unsupported_candidate_tech_claims(self, context: RunContext, content: str) -> list[str]:
        support_text = self._current_resume_support_text(context)
        if not support_text.strip():
            return []
        normalized_support = _normalize_fact_text(support_text)
        unsupported: list[str] = []
        for line in content.splitlines():
            raw_line = line.strip()
            if _line_is_report_topic_or_heading(raw_line):
                continue
            normalized_line = _normalize_fact_text(line)
            if not normalized_line:
                continue
            if _line_is_jd_only(normalized_line) or _line_is_gap_or_negative(normalized_line):
                continue
            if not _line_looks_like_candidate_claim(normalized_line):
                continue
            for canonical, aliases in _CANDIDATE_TECH_TERMS.items():
                if _first_present_alias(normalized_line, aliases) is None:
                    continue
                if _first_present_alias(normalized_support, aliases) is not None:
                    continue
                _append_unique(unsupported, f"{canonical}: {_truncate_text(line.strip(), 90)}")
        return unsupported

    def _supported_candidate_facts(self, context: RunContext) -> list[str]:
        support_text = self._current_resume_support_text(context)
        if not support_text.strip():
            return []
        normalized_support = _normalize_fact_text(support_text)
        facts: list[str] = []
        for display, aliases in _CANDIDATE_SUPPORT_TERMS.items():
            if _first_present_alias(normalized_support, aliases) is not None:
                facts.append(display)
        return facts[:12]

    def _current_resume_support_text(self, context: RunContext) -> str:
        parts: list[str] = []
        for profile in self._career_store.list_resume_profiles():
            if getattr(profile, "source_session_id", None) != context.session_id:
                continue
            if getattr(profile, "status", None) != CareerRecordStatus.ACTIVE:
                continue
            parts.append(json.dumps(_record_payload(profile), ensure_ascii=False, sort_keys=True))
            for artifact_id in (profile.source_artifact_id, profile.raw_text_artifact_id):
                if not isinstance(artifact_id, str) or not artifact_id.strip():
                    continue
                try:
                    parts.append(self._session_repository.read_session_artifact_text(context.session_id, artifact_id))
                except (SessionNotFoundError, StorageError, ValidationError):
                    continue
        return "\n".join(parts)

    def _block_child_pasted_text_artifact(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        recent_artifacts = [
            {
                "artifact_id": artifact.artifact_id,
                "title": artifact.title,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "status": artifact.status,
            }
            for artifact in self._session_repository.list_session_artifacts(context.session_id)[-5:]
        ]
        payload = {
            "workflow_runtime_result": True,
            "policy": "block",
            "skipped": True,
            "tool": "session_create_text_artifact",
            "reason": "child_agent_cannot_create_pasted_text",
            "message": (
                "未创建 pasted_text artifact：子 Agent 不能伪造用户输入资料。"
                "请读取 active_artifacts 或 recent_artifacts 中已有资料；如需输出报告，只能创建 generated_file。"
            ),
            "recent_artifacts": recent_artifacts,
        }
        return WorkflowGuardDecision(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name="session_create_text_artifact",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            ),
            event_payload={
                "workflow_runtime_result": True,
                "policy": "block",
                "tool_name": "session_create_text_artifact",
                "reason": "child_agent_cannot_create_pasted_text",
                "skipped": True,
                "recent_artifact_count": len(recent_artifacts),
            },
        )

    def _inspect_resume_profile_save(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        source_artifact_id = _string_or_none(args.get("source_artifact_id"))
        if source_artifact_id is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        existing = _find_one(
            self._career_store.list_resume_profiles(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and item.source_artifact_id == source_artifact_id,
        )
        if existing is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        return _reuse_decision(
            tool_call,
            tool_name="career_resume_profile_save",
            record_type="resume_profile",
            record_id=existing.resume_profile_id,
            record=existing,
            lock_key=f"resume_profile:{source_artifact_id}",
        )

    def _inspect_jd_analysis_save(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        source_artifact_id = _string_or_none(args.get("source_artifact_id"))
        if source_artifact_id is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        existing = _find_one(
            self._career_store.list_jd_analyses(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and item.source_artifact_id == source_artifact_id,
        )
        if existing is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        return _reuse_decision(
            tool_call,
            tool_name="career_jd_analysis_save",
            record_type="jd_analysis",
            record_id=existing.jd_analysis_id,
            record=existing,
            lock_key=f"jd_analysis:{source_artifact_id}",
        )

    def _inspect_job_fit_report_save(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        repair_actions: list[dict[str, str]] = []
        args, repair_actions = self._repair_jd_and_resume_refs(args, context, repair_actions)
        jd_analysis_id = _string_or_none(args.get("jd_analysis_id"))
        resume_profile_id = _string_or_none(args.get("resume_profile_id"))
        report_artifact_id = _string_or_none(args.get("report_artifact_id"))
        source_artifact_id = _string_or_none(args.get("source_artifact_id"))

        existing = _find_one(
            self._career_store.list_job_fit_reports(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and (
                (
                    jd_analysis_id is not None
                    and resume_profile_id is not None
                    and item.jd_analysis_id == jd_analysis_id
                    and item.resume_profile_id == resume_profile_id
                )
                or (report_artifact_id is not None and item.report_artifact_id == report_artifact_id)
                or (source_artifact_id is not None and item.source_artifact_id == source_artifact_id)
            ),
        )
        if existing is not None:
            return _reuse_decision(
                tool_call,
                tool_name="career_job_fit_report_save",
                record_type="job_fit_report",
                record_id=existing.job_fit_report_id,
                record=existing,
                lock_key=f"job_fit_report:{existing.resume_profile_id}:{existing.jd_analysis_id}",
                repair_actions=repair_actions,
            )
        repaired_call = _replace_arguments(tool_call, args) if repair_actions else tool_call
        return _repair_decision(tool_call, repaired_call, repair_actions)

    def _inspect_application_create(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        repair_actions: list[dict[str, str]] = []
        args, repair_actions = self._repair_fit_ref(args, context, repair_actions)
        args, repair_actions = self._repair_jd_and_resume_refs(args, context, repair_actions)

        jd_analysis_id = _string_or_none(args.get("jd_analysis_id"))
        resume_profile_id = _string_or_none(args.get("resume_profile_id"))
        job_fit_report_id = _string_or_none(args.get("job_fit_report_id"))
        existing = _find_one(
            self._career_store.list_career_applications(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and (
                (job_fit_report_id is not None and item.job_fit_report_id == job_fit_report_id)
                or (
                    jd_analysis_id is not None
                    and resume_profile_id is not None
                    and item.jd_analysis_id == jd_analysis_id
                    and item.resume_profile_id == resume_profile_id
                )
            ),
        )
        if existing is not None:
            return _reuse_decision(
                tool_call,
                tool_name="career_application_create",
                record_type="career_application",
                record_id=existing.application_id,
                record=existing,
                lock_key=f"career_application:{existing.resume_profile_id}:{existing.jd_analysis_id}",
                repair_actions=repair_actions,
            )
        repaired_call = _replace_arguments(tool_call, args) if repair_actions else tool_call
        return _repair_decision(tool_call, repaired_call, repair_actions)

    def _inspect_career_profile_merge(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        raw_updates = args.get("updates")
        if not isinstance(raw_updates, dict):
            return WorkflowGuardDecision(tool_call=tool_call)
        updates: dict[str, Any] = {}
        dropped_fields: list[str] = []
        for raw_key, value in raw_updates.items():
            if not isinstance(raw_key, str) or not raw_key.strip():
                dropped_fields.append(str(raw_key))
                continue
            source_key = raw_key.strip()
            target_key = _CAREER_PROFILE_UPDATE_ALIASES.get(source_key, source_key)
            if target_key in _CAREER_PROFILE_IGNORED_UPDATE_FIELDS:
                dropped_fields.append(source_key)
                continue
            if target_key not in _CAREER_PROFILE_ALLOWED_UPDATE_FIELDS:
                dropped_fields.append(source_key)
                continue
            updates[source_key] = value
        if not dropped_fields:
            return WorkflowGuardDecision(tool_call=tool_call)
        if not updates:
            return _block_decision(
                tool_call,
                tool_name="career_profile_merge",
                reason="career_profile_merge_no_supported_updates",
                next_action="updates 中没有 CareerProfile 支持的字段；请只使用 target_roles、skills、strengths、weaknesses 等受控字段。",
                missing_outputs=["career_profile"],
                lock_key=f"career_profile_merge_empty_supported_updates:{context.run_id}",
                extra_payload={"next_allowed_tools": ["career_profile_merge"]},
                extra_event_payload={"next_allowed_tools": ["career_profile_merge"]},
            )
        args["updates"] = updates
        repair_actions = [
            {
                "field": "updates",
                "from": ",".join(dict.fromkeys(dropped_fields)),
                "to": "supported_career_profile_fields",
                "reason": "career_profile_merge_unsupported_fields_removed",
            }
        ]
        return _repair_decision(tool_call, _replace_arguments(tool_call, args), repair_actions)

    def _inspect_application_merge(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        current_user_message = self._latest_user_message(context)
        if context.agent_id != context.entry_agent_id or not _is_resume_version_intent(current_user_message):
            return WorkflowGuardDecision(tool_call=tool_call)
        if _allows_new_resume_version(current_user_message):
            return WorkflowGuardDecision(tool_call=tool_call)
        active_versions = [
            item
            for item in self._career_store.list_resume_versions()
            if item.source_session_id == context.session_id and item.status == CareerRecordStatus.ACTIVE
        ]
        if active_versions:
            return self._repair_resume_version_application_merge(tool_call, context, active_versions)
        return _block_decision(
            tool_call,
            tool_name="career_application_merge",
            reason="resume_version_merge_without_record",
            next_action=(
                "当前会话还没有真实 ResumeVersion 记录；不要合并或编造 resume_version_id/artifact_id。"
                "先调用 career_resume_version_create，并且只有该工具返回 record_type=resume_version 后才能 merge。"
            ),
            missing_outputs=["resume_version"],
            lock_key=f"resume_version_merge_without_record:{context.run_id}",
        )

    def _repair_resume_version_application_merge(
        self,
        tool_call: ToolCall,
        context: RunContext,
        active_versions: list[Any],
    ) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        repair_actions: list[dict[str, str]] = []
        current_version = sorted(active_versions, key=lambda item: getattr(item, "updated_at", datetime.min), reverse=True)[0]
        raw_version_id = getattr(current_version, "resume_version_id", None)
        version_id = raw_version_id if isinstance(raw_version_id, str) and raw_version_id.strip() else None
        if version_id is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        application = _single_current_session_record(self._career_store.list_career_applications(), context.session_id)
        if application is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        raw_application_id = getattr(application, "application_id", None)
        application_id = raw_application_id if isinstance(raw_application_id, str) and raw_application_id.strip() else None
        if application_id is None:
            return WorkflowGuardDecision(tool_call=tool_call)
        if _string_or_none(args.get("application_id")) != application_id:
            previous = _string_or_none(args.get("application_id")) or ""
            args["application_id"] = application_id
            repair_actions.append(
                {
                    "field": "application_id",
                    "from": previous,
                    "to": application_id,
                    "reason": "single_current_session_application_for_resume_version_merge",
                }
            )
        raw_updates = args.get("updates")
        updates = dict(raw_updates) if isinstance(raw_updates, dict) else {}
        raw_version_ids = updates.get("resume_version_ids")
        if not isinstance(raw_version_ids, list) or version_id not in raw_version_ids:
            merged_version_ids = [item for item in raw_version_ids if isinstance(item, str)] if isinstance(raw_version_ids, list) else []
            if version_id not in merged_version_ids:
                merged_version_ids.append(version_id)
            updates["resume_version_ids"] = merged_version_ids
            args["updates"] = updates
            repair_actions.append(
                {
                    "field": "updates.resume_version_ids",
                    "from": "" if not isinstance(raw_version_ids, list) else ",".join(str(item) for item in raw_version_ids),
                    "to": version_id,
                    "reason": "current_resume_version_for_application_merge",
                }
            )
        raw_refs = args.get("evidence_refs")
        refs = list(raw_refs) if isinstance(raw_refs, list) else []
        if version_id not in refs:
            refs.append(version_id)
            args["evidence_refs"] = refs
            repair_actions.append(
                {
                    "field": "evidence_refs",
                    "from": "missing_resume_version_id",
                    "to": version_id,
                    "reason": "current_resume_version_evidence_for_application_merge",
                }
            )
        if not repair_actions:
            return WorkflowGuardDecision(tool_call=tool_call)
        return _repair_decision(tool_call, _replace_arguments(tool_call, args), repair_actions)

    def _inspect_resume_version_create(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        repair_actions: list[dict[str, str]] = []
        current_user_message = self._latest_user_message(context)
        if _is_jd_fit_only_intent(current_user_message):
            return _block_decision(
                tool_call,
                tool_name="career_resume_version_create",
                reason="jd_fit_stage_blocks_resume_version",
                next_action="本轮只完成 JDAnalysis、JobFitReport 和 CareerApplication；等用户要求定制简历时再创建 ResumeVersion。",
                missing_outputs=[],
                lock_key=f"resume_version_stage:{context.run_id}",
            )
        args, repair_actions = self._repair_jd_and_resume_refs(
            args,
            context,
            repair_actions,
            jd_field="target_jd_analysis_id",
            resume_field="base_resume_profile_id",
        )
        args, repair_actions = self._repair_missing_resume_version_refs(args, context, repair_actions)
        base_resume_profile_id = _string_or_none(args.get("base_resume_profile_id")) or _string_or_none(
            args.get("resume_profile_id")
        )
        target_jd_analysis_id = _string_or_none(args.get("target_jd_analysis_id"))
        if base_resume_profile_id is not None and target_jd_analysis_id is None:
            return _block_decision(
                tool_call,
                tool_name="career_resume_version_create",
                reason="resume_version_missing_target_jd_analysis_id",
                next_action="先确认 target_jd_analysis_id；可从当前求职项目、evidence_refs 或 JDAnalysis 列表中选择一个明确 JDAnalysis。",
                missing_outputs=["target_jd_analysis_id"],
                lock_key=f"resume_version_target_jd:{base_resume_profile_id}:{context.run_id}",
                repair_actions=repair_actions,
            )
        existing = _find_one(
            self._career_store.list_resume_versions(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and item.base_resume_profile_id == base_resume_profile_id
            and item.target_jd_analysis_id == target_jd_analysis_id,
        )
        if existing is not None:
            if not _allows_new_resume_version(current_user_message):
                return _reuse_decision(
                    tool_call,
                    tool_name="career_resume_version_create",
                    record_type="resume_version",
                    record_id=existing.resume_version_id,
                    record=existing,
                    lock_key=f"resume_version:{existing.base_resume_profile_id}:{existing.target_jd_analysis_id}",
                    policy="reuse",
                    repair_actions=repair_actions,
                )
        if _string_or_none(args.get("content")) is None and _string_or_none(args.get("artifact_id")) is None:
            compacted_fields = [
                field_name
                for field_name in ("content_omitted", "content_preview", "content_chars")
                if field_name in args
            ]
            if compacted_fields and self._current_run_resume_version_validation_failure_count(context) > 0:
                for field_name in compacted_fields:
                    args.pop(field_name, None)
                repair_actions.append(
                    {
                        "field": "content",
                        "from": ",".join(compacted_fields),
                        "to": "tool_safe_fallback",
                        "reason": "resume_version_compacted_content_ignored_after_validation_failure",
                    }
                )
                return _repair_decision(tool_call, _replace_arguments(tool_call, args), repair_actions)
            reason = (
                "resume_version_compacted_content_not_usable"
                if compacted_fields
                else "resume_version_missing_content_or_artifact"
            )
            return _block_decision(
                tool_call,
                tool_name="career_resume_version_create",
                reason=reason,
                next_action=(
                    "career_resume_version_create 必须传完整 Markdown content，或传已存在的 generated_file artifact_id。"
                    "content_omitted/content_preview/content_chars 只是历史压缩摘要，不能作为简历正文。"
                ),
                missing_outputs=["resume_version"],
                lock_key=f"resume_version_missing_content:{context.run_id}",
                repair_actions=repair_actions,
                extra_payload={
                    "next_allowed_tools": ["career_resume_version_create"],
                    "required_tools": ["career_resume_version_create"],
                    "compacted_fields": compacted_fields,
                },
                extra_event_payload={
                    "next_allowed_tools": ["career_resume_version_create"],
                    "missing_outputs": ["resume_version"],
                    "compacted_fields": compacted_fields,
                },
            )
        if base_resume_profile_id is not None and target_jd_analysis_id is not None:
            prerequisite_decision = self._inspect_resume_version_prerequisites(
                tool_call,
                context,
                base_resume_profile_id=base_resume_profile_id,
                target_jd_analysis_id=target_jd_analysis_id,
                repair_actions=repair_actions,
            )
            if prerequisite_decision is not None:
                return prerequisite_decision
        repaired_call = _replace_arguments(tool_call, args) if repair_actions else tool_call
        return _repair_decision(tool_call, repaired_call, repair_actions)

    def _current_run_resume_version_validation_failure_count(self, context: RunContext) -> int:
        count = 0
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "tool_result":
                continue
            payload = event.payload
            if payload.get("tool_name") != "career_resume_version_create" or payload.get("success") is not False:
                continue
            content = payload.get("content")
            if isinstance(content, str) and "ResumeVersion validation failed" in content:
                count += 1
        return count

    def _repair_missing_resume_version_refs(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        args, repair_actions = self._repair_missing_record_ref(
            args,
            context,
            repair_actions,
            field="base_resume_profile_id",
            evidence_prefix="resume_profile_",
            records=self._career_store.list_resume_profiles(),
            getter=self._career_store.get_resume_profile,
            id_attr="resume_profile_id",
            reason="current_session_resume_profile_for_resume_version",
        )
        args, repair_actions = self._repair_missing_record_ref(
            args,
            context,
            repair_actions,
            field="target_jd_analysis_id",
            evidence_prefix="jd_",
            records=self._career_store.list_jd_analyses(),
            getter=self._career_store.get_jd_analysis,
            id_attr="jd_analysis_id",
            reason="current_session_jd_analysis_for_resume_version",
        )
        return args, repair_actions

    def _repair_missing_record_ref(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
        *,
        field: str,
        evidence_prefix: str,
        records: list[Any],
        getter: Callable[[str], Any | None],
        id_attr: str,
        reason: str,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        if _string_or_none(args.get(field)) is not None:
            return args, repair_actions
        repaired = self._single_current_ref_from_evidence(
            args,
            context,
            prefix=evidence_prefix,
            getter=getter,
            id_attr=id_attr,
        )
        if repaired is None:
            fallback = _single_current_session_record(records, context.session_id)
            if fallback is not None:
                raw_repaired = getattr(fallback, id_attr, None)
                repaired = raw_repaired if isinstance(raw_repaired, str) and raw_repaired.strip() else None
        if repaired is None:
            return args, repair_actions
        args[field] = repaired
        _append_evidence_id(args, repaired)
        repair_actions.append({"field": field, "from": "", "to": repaired, "reason": reason})
        return args, repair_actions

    def _single_current_ref_from_evidence(
        self,
        args: dict[str, Any],
        context: RunContext,
        *,
        prefix: str,
        getter: Callable[[str], Any | None],
        id_attr: str,
    ) -> str | None:
        refs = args.get("evidence_refs")
        if not isinstance(refs, list):
            return None
        candidates: list[str] = []
        for ref in refs:
            if not isinstance(ref, str) or not ref.startswith(prefix):
                continue
            record = _current_record_by_id(getter, ref, context.session_id)
            if record is None:
                continue
            value = getattr(record, id_attr, None)
            if isinstance(value, str) and value not in candidates:
                candidates.append(value)
        return candidates[0] if len(candidates) == 1 else None

    def _inspect_resume_version_prerequisites(
        self,
        tool_call: ToolCall,
        context: RunContext,
        *,
        base_resume_profile_id: str,
        target_jd_analysis_id: str,
        repair_actions: list[dict[str, str]],
    ) -> WorkflowGuardDecision | None:
        fit_report = _find_one(
            self._career_store.list_job_fit_reports(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and item.resume_profile_id == base_resume_profile_id
            and item.jd_analysis_id == target_jd_analysis_id,
        )
        if fit_report is None:
            return _block_decision(
                tool_call,
                tool_name="career_resume_version_create",
                reason="resume_version_missing_job_fit_report",
                next_action="先保存 JobFitReport，再生成 ResumeVersion。",
                missing_outputs=["job_fit_report"],
                lock_key=f"resume_version_prerequisites:{base_resume_profile_id}:{target_jd_analysis_id}",
                repair_actions=repair_actions,
            )

        application = _find_one(
            self._career_store.list_career_applications(),
            lambda item: item.source_session_id == context.session_id
            and item.status == CareerRecordStatus.ACTIVE
            and item.resume_profile_id == base_resume_profile_id
            and item.jd_analysis_id == target_jd_analysis_id
            and item.job_fit_report_id == fit_report.job_fit_report_id,
        )
        if application is None:
            return _block_decision(
                tool_call,
                tool_name="career_resume_version_create",
                reason="resume_version_missing_career_application",
                next_action="先创建 CareerApplication，把 ResumeProfile、JDAnalysis 和 JobFitReport 串起来。",
                missing_outputs=["career_application"],
                lock_key=f"resume_version_prerequisites:{base_resume_profile_id}:{target_jd_analysis_id}",
                repair_actions=repair_actions,
            )
        return None

    def _inspect_delegate_agents(self, tool_call: ToolCall, context: RunContext) -> WorkflowGuardDecision:
        args = _copy_arguments(tool_call.arguments)
        repair_actions: list[dict[str, str]] = []
        args, repair_actions = self._repair_delegate_artifact_refs(args, repair_actions)
        args, repair_actions = self._repair_delegate_jd_fit_task(args, context, repair_actions)
        repaired_call = _replace_arguments(tool_call, args) if repair_actions else tool_call

        signature = _delegate_signature(repaired_call.arguments)
        if signature is None:
            return _repair_decision(tool_call, repaired_call, repair_actions)
        previous = self._latest_delegate_result_for_signature(context, signature)
        jd_fit_intent = _is_jd_fit_only_intent(self._latest_user_message(context))
        if previous is not None and jd_fit_intent:
            if _single_current_session_record(self._career_store.list_job_fit_reports(), context.session_id) is None:
                previous = None
        if previous is None:
            return _repair_decision(tool_call, repaired_call, repair_actions)
        payload = dict(previous)
        payload.update(
            {
                "workflow_runtime_result": True,
                "policy": "reuse",
                "idempotent_reused": True,
                "lock_key": f"delegate_agents:{signature}",
                "message": "已复用同一 run 内相同 artifact_refs 和 target_agent_id 的委派结果，避免重复委派。",
            }
        )
        return WorkflowGuardDecision(
            tool_call=tool_call,
            result=ToolExecutionResult(
                tool_name="delegate_agents",
                success=True,
                content=json.dumps(payload, ensure_ascii=False),
            ),
            event_payload={
                "workflow_runtime_result": True,
                "policy": "reuse",
                "tool_name": "delegate_agents",
                "lock_key": f"delegate_agents:{signature}",
                "repair_actions": repair_actions,
            },
        )

    def _repair_delegate_artifact_refs(
        self,
        args: dict[str, Any],
        repair_actions: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list):
            return args, repair_actions
        changed = False
        tasks: list[Any] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                tasks.append(raw_task)
                continue
            task = dict(raw_task)
            refs = task.get("artifact_refs")
            if not isinstance(refs, list):
                tasks.append(task)
                continue
            kept_refs: list[Any] = []
            moved_product_refs: list[str] = []
            for ref in refs:
                if isinstance(ref, str) and _is_product_record_ref(ref):
                    moved_product_refs.append(ref)
                    continue
                kept_refs.append(ref)
            if moved_product_refs:
                task["artifact_refs"] = kept_refs
                instruction = _string_or_none(task.get("instruction")) or ""
                refs_text = ", ".join(moved_product_refs)
                if not all(ref in instruction for ref in moved_product_refs):
                    addition = (
                        "\n\nWorkflowRuntime 修正：以下是产品记录 id，不是 artifact_refs，"
                        f"请仅在正文中使用：{refs_text}。"
                    )
                    task["instruction"] = f"{instruction}{addition}" if instruction else addition.strip()
                changed = True
            tasks.append(task)
        if not changed:
            return args, repair_actions
        args["tasks"] = tasks
        repair_actions.append(
            {
                "field": "delegate_agents.tasks[].artifact_refs",
                "from": "artifact_refs_with_product_ids",
                "to": "artifact_refs_only",
                "reason": "delegate_artifact_refs_accept_only_session_artifacts",
            }
        )
        return args, repair_actions

    def _job_fit_report_generation_contract(self, context: RunContext) -> str:
        supported_facts = self._supported_candidate_facts(context)
        fact_text = (
            "、".join(supported_facts)
            if supported_facts
            else "只能使用 ResumeProfile、CareerProfile 和简历 artifact 中明确出现的事实"
        )
        return (
            "WorkflowRuntime 输出边界：JDAnalysis 是产品记录，不要为 JDAnalysis 单独创建用户可见 artifact。"
            "当前子任务只允许生成一个用户可预览的岗位匹配报告 artifact，"
            "并在 JobFitReport.report_artifact_id 中引用该 artifact。"
            f"报告里的“已匹配/候选人已有能力”只能来自 supported_candidate_facts：{fact_text}；"
            "JD 中未出现在这些事实里的要求，只能写入 gaps、风险、建议或待确认。"
            "调用 session_create_text_artifact 时必须把完整 Markdown 正文传入 content 字段，"
            "不要传 content_chars、content_omitted 或占位正文。"
            "artifact 创建成功后立即调用 career_job_fit_report_save，不要再次创建或重写报告 artifact。"
        )

    def _repair_delegate_jd_fit_task(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        jd_fit_intent = _is_jd_fit_only_intent(self._latest_user_message(context))
        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list):
            return args, repair_actions

        boundary_changed = False
        boundary_tasks: list[Any] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                boundary_tasks.append(raw_task)
                continue
            task = dict(raw_task)
            if _string_or_none(task.get("target_agent_id")) != "job_agent":
                boundary_tasks.append(task)
                continue
            instruction = _string_or_none(task.get("instruction")) or ""
            if _task_requires_job_fit_report(instruction) and not _task_has_single_fit_artifact_boundary(instruction):
                addition = "\n\n" + self._job_fit_report_generation_contract(context)
                task["instruction"] = f"{instruction}{addition}" if instruction else addition.strip()
                boundary_changed = True
            boundary_tasks.append(task)
        if boundary_changed:
            args["tasks"] = boundary_tasks
            repair_actions.append(
                {
                    "field": "delegate_agents.tasks[].instruction",
                    "from": "separate_jd_analysis_artifact_allowed",
                    "to": "single_job_fit_report_artifact",
                    "reason": "jd_fit_stage_uses_single_user_visible_report_artifact",
                }
            )

        if _single_current_session_record(self._career_store.list_job_fit_reports(), context.session_id) is not None:
            return args, repair_actions
        resume_profile = _single_current_session_record(self._career_store.list_resume_profiles(), context.session_id)
        career_profile = _single_current_session_record(self._career_store.list_career_profiles(), context.session_id)
        if resume_profile is None or career_profile is None:
            return args, repair_actions
        raw_resume_profile_id = getattr(resume_profile, "resume_profile_id", None)
        raw_career_profile_id = getattr(career_profile, "career_profile_id", None)
        if not isinstance(raw_resume_profile_id, str) or not isinstance(raw_career_profile_id, str):
            return args, repair_actions

        raw_tasks = args.get("tasks")
        if not isinstance(raw_tasks, list):
            return args, repair_actions
        changed = False
        completion_changed = False
        replaced_instruction_refs: list[str] = []
        tasks: list[Any] = []
        for raw_task in raw_tasks:
            if not isinstance(raw_task, dict):
                tasks.append(raw_task)
                continue
            task = dict(raw_task)
            if _string_or_none(task.get("target_agent_id")) != "job_agent":
                tasks.append(task)
                continue
            instruction = _string_or_none(task.get("instruction")) or ""
            instruction, resume_refs_changed = _replace_product_refs_in_text(
                instruction,
                prefix="resume_profile_",
                replacement=raw_resume_profile_id,
            )
            instruction, career_refs_changed = _replace_product_refs_in_text(
                instruction,
                prefix="career_profile_",
                replacement=raw_career_profile_id,
            )
            if resume_refs_changed or career_refs_changed:
                task["instruction"] = instruction
                replaced_instruction_refs.extend(resume_refs_changed)
                replaced_instruction_refs.extend(career_refs_changed)
                changed = True
            if not jd_fit_intent:
                tasks.append(task)
                continue
            lowered_instruction = instruction.casefold()
            if _has_all(
                lowered_instruction,
                (
                    "career_jd_analysis_save",
                    "career_job_fit_report_save",
                    "jobfitreport",
                ),
            ) or _has_all(
                lowered_instruction,
                (
                    "career_jd_analysis_save",
                    "career_job_fit_report_save",
                    "匹配报告",
                ),
            ):
                tasks.append(task)
                continue
            jd_artifact_id = _jd_artifact_ref_from_task(task)
            addition = (
                "\n\nWorkflowRuntime 阶段要求：当前是 JD 匹配阶段，请一次性完成 JDAnalysis 和 JobFitReport，"
                "不要只保存 JDAnalysis 后结束。必须调用 career_jd_analysis_save 保存 JDAnalysis，"
                "并调用 career_job_fit_report_save 保存 JobFitReport。"
                f" 使用 resume_profile_id={raw_resume_profile_id}，career_profile_id={raw_career_profile_id}。"
                " 只生成一个用户可预览的匹配报告 artifact，然后立刻在 JobFitReport.report_artifact_id 中引用；"
                "不要创建单独 JD 分析 artifact，也不要反复重写或创建多个匹配报告 artifact。"
            )
            if jd_artifact_id is not None:
                addition += f" JDAnalysis.source_artifact_id 必须使用 {jd_artifact_id}。"
            task["instruction"] = f"{instruction}{addition}" if instruction else addition.strip()
            tasks.append(task)
            changed = True
            completion_changed = True
        if not changed:
            return args, repair_actions
        args["tasks"] = tasks
        if replaced_instruction_refs:
            repair_actions.append(
                {
                    "field": "delegate_agents.tasks[].instruction",
                    "from": ",".join(dict.fromkeys(replaced_instruction_refs)),
                    "to": f"{raw_resume_profile_id},{raw_career_profile_id}",
                    "reason": "delegate_instruction_product_refs_repaired",
                }
            )
        if completion_changed:
            repair_actions.append(
                {
                    "field": "delegate_agents.tasks[].instruction",
                    "from": "jd_analysis_only",
                    "to": "jd_analysis_and_job_fit_report",
                    "reason": "jd_fit_stage_requires_single_job_agent_completion",
                }
            )
        return args, repair_actions

    def _repair_fit_ref(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        raw_id = _string_or_none(args.get("job_fit_report_id"))
        if raw_id is None:
            return args, repair_actions
        current = _current_record_by_id(self._career_store.get_job_fit_report, raw_id, context.session_id)
        if current is not None:
            return args, repair_actions
        fallback = _single_current_session_record(self._career_store.list_job_fit_reports(), context.session_id)
        if fallback is None:
            return args, repair_actions
        args["job_fit_report_id"] = fallback.job_fit_report_id
        _replace_evidence_id(args, old_id=raw_id, new_id=fallback.job_fit_report_id, prefix="fit_")
        repair_actions.append(
            {
                "field": "job_fit_report_id",
                "from": raw_id,
                "to": fallback.job_fit_report_id,
                "reason": "single_current_session_job_fit_report",
            }
        )
        return args, repair_actions

    def _repair_jd_and_resume_refs(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
        *,
        jd_field: str = "jd_analysis_id",
        resume_field: str = "resume_profile_id",
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        args, repair_actions = self._repair_record_ref(
            args,
            context,
            repair_actions,
            field=jd_field,
            prefix="jd_",
            records=self._career_store.list_jd_analyses(),
            getter=self._career_store.get_jd_analysis,
            id_attr="jd_analysis_id",
            reason="single_current_session_jd_analysis",
        )
        args, repair_actions = self._repair_record_ref(
            args,
            context,
            repair_actions,
            field=resume_field,
            prefix="resume_profile_",
            records=self._career_store.list_resume_profiles(),
            getter=self._career_store.get_resume_profile,
            id_attr="resume_profile_id",
            reason="single_current_session_resume_profile",
        )
        return args, repair_actions

    def _repair_record_ref(
        self,
        args: dict[str, Any],
        context: RunContext,
        repair_actions: list[dict[str, str]],
        *,
        field: str,
        prefix: str,
        records: list[Any],
        getter: Callable[[str], Any | None],
        id_attr: str,
        reason: str,
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        raw_id = _string_or_none(args.get(field))
        if raw_id is None:
            return args, repair_actions
        if _current_record_by_id(getter, raw_id, context.session_id) is not None:
            return args, repair_actions
        fallback = _single_current_session_record(records, context.session_id)
        if fallback is None:
            return args, repair_actions
        repaired_id = getattr(fallback, id_attr, None)
        if not isinstance(repaired_id, str) or not repaired_id:
            return args, repair_actions
        args[field] = repaired_id
        _replace_evidence_id(args, old_id=raw_id, new_id=repaired_id, prefix=prefix)
        repair_actions.append({"field": field, "from": raw_id, "to": repaired_id, "reason": reason})
        return args, repair_actions

    def _latest_delegate_result_for_signature(self, context: RunContext, signature: str) -> dict[str, Any] | None:
        call_args_by_id: dict[str, Any] = {}
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type == "tool_call" and event.payload.get("name") == "delegate_agents":
                call_id = event.payload.get("tool_call_id")
                if isinstance(call_id, str):
                    call_args_by_id[call_id] = event.payload.get("arguments")
                continue
            if event.type != "tool_result" or event.payload.get("tool_name") != "delegate_agents":
                continue
            if event.payload.get("success") is not True:
                continue
            call_id = event.payload.get("tool_call_id")
            if not isinstance(call_id, str) or _delegate_signature(call_args_by_id.get(call_id)) != signature:
                continue
            payload = _loads_json_object(event.payload.get("content"))
            if payload is None or payload.get("status") not in {"completed", "skipped"}:
                continue
            return payload
        return None

    def _latest_user_message(self, context: RunContext) -> str:
        message = ""
        for event in self._session_repository.list_run_events(context.session_id, context.agent_id, context.run_id):
            if event.type != "user_message":
                continue
            content = event.payload.get("content")
            if isinstance(content, str) and content.strip():
                message = content.strip()
        return message


def _reuse_decision(
    tool_call: ToolCall,
    *,
    tool_name: str,
    record_type: str,
    record_id: str,
    record: Any,
    lock_key: str,
    policy: str = "reuse",
    repair_actions: list[dict[str, str]] | None = None,
) -> WorkflowGuardDecision:
    payload = {
        "record_type": record_type,
        "record_id": record_id,
        "found": True,
        "status": getattr(record, "status", ""),
        "source_session_id": getattr(record, "source_session_id", None),
        "source_artifact_id": getattr(record, "source_artifact_id", None),
        "record": _record_payload(record),
        "workflow_runtime_result": True,
        "policy": policy,
        "idempotent_reused": True,
        "lock_key": lock_key,
        "repair_actions": repair_actions or [],
    }
    return WorkflowGuardDecision(
        tool_call=tool_call,
        result=ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            content=json.dumps(_jsonable(payload), ensure_ascii=False),
        ),
        event_payload={
            "workflow_runtime_result": True,
            "policy": policy,
            "tool_name": tool_name,
            "lock_key": lock_key,
            "record_type": record_type,
            "record_id": record_id,
            "repair_actions": repair_actions or [],
        },
    )


def _block_decision(
    tool_call: ToolCall,
    *,
    tool_name: str,
    reason: str,
    next_action: str,
    missing_outputs: list[str],
    lock_key: str,
    repair_actions: list[dict[str, str]] | None = None,
    extra_payload: dict[str, Any] | None = None,
    extra_event_payload: dict[str, Any] | None = None,
) -> WorkflowGuardDecision:
    payload = {
        "workflow_runtime_result": True,
        "policy": "block",
        "recoverable": True,
        "skipped": True,
        "tool_executed": False,
        "result_created": False,
        "tool": tool_name,
        "reason": reason,
        "next_action": next_action,
        "missing_outputs": missing_outputs,
        "lock_key": lock_key,
        "repair_actions": repair_actions or [],
    }
    payload.update(extra_payload or {})
    event_payload = {
        "workflow_runtime_result": True,
        "policy": "block",
        "tool_name": tool_name,
        "reason": reason,
        "lock_key": lock_key,
        "missing_outputs": missing_outputs,
        "repair_actions": repair_actions or [],
    }
    event_payload.update(extra_event_payload or {})
    return WorkflowGuardDecision(
        tool_call=tool_call,
        result=ToolExecutionResult(
            tool_name=tool_name,
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        ),
        event_payload=event_payload,
    )


def _repair_decision(
    original_call: ToolCall,
    repaired_call: ToolCall,
    repair_actions: list[dict[str, str]],
) -> WorkflowGuardDecision:
    if not repair_actions:
        return WorkflowGuardDecision(tool_call=original_call)
    return WorkflowGuardDecision(
        tool_call=repaired_call,
        event_payload={
            "workflow_runtime_result": True,
            "policy": "repair",
            "tool_name": original_call.name,
            "repair_actions": repair_actions,
        },
    )


def _record_payload(record: Any) -> dict[str, Any]:
    if is_dataclass(record) and not isinstance(record, type):
        return cast(dict[str, Any], _jsonable(asdict(cast(Any, record))))
    jsonable_record = _jsonable(record)
    if isinstance(jsonable_record, dict):
        return cast(dict[str, Any], jsonable_record)
    return {"value": jsonable_record}


def _payload_record_id(payload: dict[str, Any], id_field: str) -> str | None:
    raw_value = payload.get(id_field)
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    raw_record_id = payload.get("record_id")
    if isinstance(raw_record_id, str) and raw_record_id.strip():
        return raw_record_id.strip()
    record = payload.get("record")
    if isinstance(record, dict):
        record_value = record.get(id_field)
        if isinstance(record_value, str) and record_value.strip():
            return record_value.strip()
    ids = payload.get("ids")
    if isinstance(ids, dict):
        ids_value = ids.get(id_field)
        if isinstance(ids_value, str) and ids_value.strip():
            return ids_value.strip()
    return None


def _payload_ids(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for source in (payload, payload.get("record"), payload.get("ids")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if not isinstance(key, str):
                continue
            if key == "source_session_id" or value is None:
                continue
            if key.endswith("_id") or key.endswith("_ids") or key == "record_id":
                output.setdefault(key, value)
    return output


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _copy_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        return {}
    return dict(arguments)


def _replace_arguments(tool_call: ToolCall, arguments: dict[str, Any]) -> ToolCall:
    return replace(tool_call, arguments=arguments)


def _replace_evidence_id(args: dict[str, Any], *, old_id: str, new_id: str, prefix: str) -> None:
    raw_refs = args.get("evidence_refs")
    if not isinstance(raw_refs, list):
        return
    output: list[Any] = []
    for ref in raw_refs:
        if ref == old_id:
            if new_id not in output:
                output.append(new_id)
            continue
        if isinstance(ref, str) and ref.startswith(prefix) and ref not in {new_id, old_id}:
            output.append(ref)
            continue
        if ref != old_id and ref not in output:
            output.append(ref)
    if new_id not in output:
        output.append(new_id)
    args["evidence_refs"] = output


def _replace_product_refs_in_text(text: str, *, prefix: str, replacement: str) -> tuple[str, list[str]]:
    if not text:
        return text, []
    pattern = re.compile(rf"\b{re.escape(prefix)}(?!id\b)[A-Za-z0-9_-]+\b")
    replaced: list[str] = []

    def _replace(match: re.Match[str]) -> str:
        value = match.group(0)
        if value == replacement:
            return value
        replaced.append(value)
        return replacement

    return pattern.sub(_replace, text), replaced


def _append_evidence_id(args: dict[str, Any], ref_id: str) -> None:
    refs = args.get("evidence_refs")
    if not isinstance(refs, list):
        args["evidence_refs"] = [ref_id]
        return
    if ref_id not in refs:
        refs.append(ref_id)


def _current_record_by_id(getter: Callable[[str], Any | None], record_id: str, session_id: str) -> Any | None:
    try:
        record = getter(record_id)
    except (StorageError, ValidationError):
        return None
    if record is None or getattr(record, "source_session_id", None) != session_id:
        return None
    if getattr(record, "status", None) != CareerRecordStatus.ACTIVE:
        return None
    return record


def _is_product_record_ref(value: str) -> bool:
    return value.startswith(
        (
            "resume_profile_",
            "career_profile_",
            "jd_",
            "fit_",
            "resume_version_",
            "application_",
            "note_",
            "learning_task_",
            "learning_plan_",
            "weakness_",
            "checkin_",
        )
    )


def _single_current_session_record(records: list[Any], session_id: str) -> Any | None:
    matches = [
        record
        for record in records
        if getattr(record, "source_session_id", None) == session_id
        and getattr(record, "status", None) == CareerRecordStatus.ACTIVE
    ]
    return matches[0] if len(matches) == 1 else None


def _find_one(records: list[Any], predicate: Callable[[Any], bool]) -> Any | None:
    matches = [record for record in records if predicate(record)]
    if not matches:
        return None
    return sorted(matches, key=lambda item: getattr(item, "updated_at", datetime.min), reverse=True)[0]


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _child_output_kind(agent_id: str, text: str) -> str | None:
    normalized = text.lower()
    compact = _normalize_fact_text(text)
    if agent_id == "job_agent" and (
        "岗位匹配" in text
        or "匹配报告" in text
        or "job fit" in normalized
        or "fit report" in normalized
    ):
        return "job_fit_report"
    if agent_id == "job_agent" and (
        "jdanalysis" in normalized
        or "jdanalysis" in compact
        or "jd分析" in compact
        or "jd分析报告" in compact
        or "岗位分析" in text
        or "岗位要求分析" in text
    ):
        return "jd_analysis_report"
    if agent_id == "resume_agent" and (
        "简历诊断" in text
        or ("简历" in text and "诊断" in text)
        or "resume diagnosis" in normalized
    ):
        return "resume_diagnosis"
    return None


_CANDIDATE_TECH_TERMS: dict[str, tuple[str, ...]] = {
    "agent": ("agent", "智能体"),
    "celery": ("celery",),
    "java": ("java",),
    "spring": ("spring", "spring boot", "springboot"),
    "docker": ("docker",),
    "kubernetes": ("kubernetes", "k8s"),
    "react": ("react",),
    "vue": ("vue",),
    "mysql": ("mysql",),
    "langchain": ("langchain",),
    "langgraph": ("langgraph",),
    "milvus": ("milvus",),
    "qdrant": ("qdrant",),
    "weaviate": ("weaviate",),
    "fastapi": ("fastapi",),
    "rag": ("rag", "检索增强"),
    "vector_search": ("向量检索", "vector search"),
}

_CANDIDATE_SUPPORT_TERMS: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "FastAPI": ("fastapi",),
    "PostgreSQL": ("postgresql",),
    "Redis": ("redis",),
    "RAG": ("rag", "检索增强生成"),
    "Agent 工具调用": ("agent 工具调用", "工具调用", "agent"),
    "多 Agent 委派": ("多 agent", "multi-agent", "委派"),
    "API 开发": ("api", "接口"),
    "任务队列": ("任务队列",),
    "日志审计": ("日志审计", "日志"),
    "部署经验": ("部署",),
    "后端开发经验": ("后端开发", "后端"),
}


def _line_is_jd_only(normalized_line: str) -> bool:
    if _has_any(normalized_line, ("候选人", "简历", "本人")):
        return False
    return _has_any(normalized_line, ("jd", "岗位", "职位", "要求", "目标岗位", "技术栈"))


def _line_is_report_topic_or_heading(line: str) -> bool:
    if not line:
        return True
    if line.startswith("#"):
        return True
    if re.fullmatch(r"[-*_\\s|:：]+", line):
        return True
    text = re.sub(r"^[-*+>\\s]+", "", line)
    text = re.sub(r"^\\d+[\\.、)]\\s*", "", text)
    text = re.sub(r"[*_`#]+", "", text).strip()
    if not text:
        return True
    if "|" in text:
        return False
    if len(text) <= 36 and not _has_any(_normalize_fact_text(text), ("候选人", "简历", "本人")):
        return True
    return False


def _line_is_gap_or_negative(normalized_line: str) -> bool:
    return _has_any(
        normalized_line,
        (
            "无",
            "未",
            "不匹配",
            "缺",
            "不足",
            "差距",
            "风险",
            "待",
            "待补齐",
            "需",
            "是否",
            "能否",
            "有没有",
            "确认",
            "待确认",
            "需确认",
            "可能",
            "影响",
            "薄弱",
            "建议",
            "参考",
            "澄清",
            "学习",
            "了解",
            "入门",
            "增加",
            "补齐",
            "补充",
            "强化",
            "提升",
            "准备",
            "说明",
            "呈现",
        ),
    )


def _line_looks_like_candidate_claim(normalized_line: str) -> bool:
    if _has_any(normalized_line, ("✓", "✅", "明确匹配", "直接匹配", "完全匹配")):
        return True
    return _has_any(
        normalized_line,
        (
            "候选人",
            "简历",
            "本人",
            "主栈",
            "为主",
            "使用",
            "掌握",
            "熟悉",
            "具备",
            "有经验",
            "项目",
            "背景",
            "能力",
            "负责",
            "开发",
        ),
    )


def _first_present_alias(normalized_text: str, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        normalized_alias = _normalize_fact_text(alias)
        if normalized_alias and normalized_alias in normalized_text:
            return alias
    return None


def _normalize_fact_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _append_unique(output: list[str], value: str) -> None:
    if value not in output:
        output.append(value)


def _truncate_text(value: str, limit: int) -> str:
    return value if len(value) <= limit else f"{value[: max(0, limit - 1)]}…"


def _delegate_signature(arguments: Any) -> str | None:
    if not isinstance(arguments, dict):
        return None
    raw_tasks = arguments.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return None
    parts: list[str] = []
    for task in raw_tasks:
        if not isinstance(task, dict):
            return None
        target_agent_id = _string_or_none(task.get("target_agent_id"))
        if target_agent_id is None:
            return None
        refs = task.get("artifact_refs")
        artifact_refs = sorted(ref for ref in refs if isinstance(ref, str)) if isinstance(refs, list) else []
        parts.append(f"{target_agent_id}:{','.join(artifact_refs)}")
    return "|".join(sorted(parts))


def _jd_artifact_ref_from_task(task: dict[str, Any]) -> str | None:
    refs = task.get("artifact_refs")
    if not isinstance(refs, list):
        return None
    string_refs = [ref for ref in refs if isinstance(ref, str) and ref.startswith("artifact_")]
    jd_refs = [ref for ref in string_refs if ref.startswith("artifact_jd")]
    if len(jd_refs) == 1:
        return jd_refs[0]
    if len(string_refs) == 1:
        return string_refs[0]
    return None


def _loads_json_object(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, str):
        return None
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _is_runtime_block_tool_result(event: Any) -> bool:
    payload = getattr(event, "payload", None)
    if not isinstance(payload, dict):
        return False
    content = payload.get("content")
    decoded = _loads_json_object(content)
    return (
        decoded is not None
        and decoded.get("workflow_runtime_result") is True
        and decoded.get("policy") == "block"
        and decoded.get("tool_executed") is False
    )


def _is_jd_fit_only_intent(message: str) -> bool:
    text = message.strip().casefold()
    if not text:
        return False
    if _has_any(text, ("定制简历", "简历版本", "生成一版简历", "改简历", "resumeversion", "resume version")):
        return False
    return _has_any(text, ("jd", "岗位", "职位", "匹配", "适配", "匹配报告", "岗位分析"))


def _task_requires_job_fit_report(text: str) -> bool:
    normalized = text.strip().casefold()
    if not normalized:
        return False
    compact = _normalize_fact_text(text)
    return _has_any(
        normalized,
        (
            "jobfitreport",
            "job fit report",
            "fit report",
            "job_fit_report",
            "career_job_fit_report_save",
        ),
    ) or _has_any(
        compact,
        (
            "岗位匹配",
            "匹配报告",
            "匹配度",
            "适配度",
            "求职匹配",
        ),
    )


def _task_has_single_fit_artifact_boundary(text: str) -> bool:
    normalized = text.strip().casefold()
    if not normalized:
        return False
    compact = _normalize_fact_text(text)
    return (
        "single_job_fit_report_artifact" in normalized
        or "只生成一个用户可预览的匹配报告artifact" in compact
        or "只允许生成一个用户可预览的岗位匹配报告artifact" in compact
        or ("不要为jdanalysis单独创建用户可见artifact" in compact)
        or ("不要创建单独jd分析artifact" in compact)
    )


def _is_resume_version_intent(message: str) -> bool:
    text = message.strip().casefold()
    if not text:
        return False
    if re.search(r"生成\s*简历\s*画像", text):
        return False
    return _has_any(
        text,
        (
            "定制简历",
            "简历版本",
            "生成一版简历",
            "改简历",
            "优化简历",
            "resumeversion",
            "resume version",
            "custom resume",
        ),
    ) or re.search(r"生成\s*(一版|一份|新版|定制|可投递|优化后)?\s*简历(?!\s*画像)", text) is not None


def _is_resume_diagnosis_intent(message: str) -> bool:
    text = message.strip().casefold()
    if not text or _is_resume_version_intent(text) or _is_jd_fit_only_intent(text):
        return False
    return _has_any(
        text,
        (
            "简历诊断",
            "诊断简历",
            "简历画像",
            "解析简历",
            "职业画像",
            "resume profile",
            "career profile",
        ),
    )


def _allows_reanalysis(message: str) -> bool:
    text = message.strip().casefold()
    if not text:
        return False
    return _has_any(
        text,
        (
            "重新分析",
            "重新诊断",
            "重新匹配",
            "重新生成报告",
            "再分析一次",
            "再诊断一次",
            "覆盖之前",
            "不要复用",
            "从头来",
            "rerun",
            "re-run",
            "reanalyze",
            "reanalyse",
        ),
    )


def _allows_new_resume_version(message: str) -> bool:
    text = message.strip().casefold()
    if not text:
        return False
    return _has_any(
        text,
        (
            "再生成一版",
            "再来一版",
            "重新生成一版",
            "第二版",
            "v2",
            "另一个版本",
            "换一种风格",
            "新版本",
            "new version",
            "another version",
        ),
    )


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _has_all(text: str, values: tuple[str, ...]) -> bool:
    return all(value in text for value in values)
