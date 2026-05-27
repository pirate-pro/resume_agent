"""Runtime-facing next tool plan for career workflow rounds."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Any

from app.core.errors import ValidationError
from app.domain.reference_ids import is_reserved_reference_value
from app.runtime.workflow.action_plan import (
    action_contract_for_phase,
    action_contract_plan_payload,
    pending_action_plan_after_tool_result,
)
from app.runtime.workflow.contracts import ActionContract
from app.runtime.workflow.phase import WorkflowPhaseSnapshot
from app.runtime.workflow.tool_hints import build_required_tool_call_hint

if TYPE_CHECKING:
    from app.runtime.context.models import CareerFlowState, CurrentWorkflowState

_FINAL_WHEN_NO_MISSING_PHASES = {
    "resume_diagnosis",
    "jd_fit",
    "resume_version",
    "note_write",
    "retrieval_read_only",
    "rag_note_write",
    "rag_learning_task_create",
    "interview_review_update",
}
__all__ = [
    "RuntimeToolPlan",
    "build_runtime_tool_plan",
    "format_runtime_tool_plan_lines",
    "is_premature_runtime_plan_answer",
    "known_refs_from_successful_tool_result",
    "merge_pending_runtime_plan",
    "pending_runtime_plan_from_context_bundle",
    "pending_runtime_plan_from_successful_tool_result",
    "pending_runtime_plan_from_tool_search_result",
    "pending_runtime_plan_from_workflow_result",
    "runtime_plan_completion_tools",
    "runtime_plan_discouraged_tools",
    "runtime_plan_next_allowed_tools",
    "workflow_incomplete_answer",
    "runtime_plan_notice",
]


@dataclass(slots=True)
class RuntimeToolPlan:
    """Compact next-action plan derived from deterministic workflow state."""

    phase: str | None = None
    known_refs: dict[str, str] = field(default_factory=dict)
    missing_outputs: list[str] = field(default_factory=list)
    next_allowed_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)
    discouraged_tools: list[str] = field(default_factory=list)
    schema_groups: list[str] = field(default_factory=list)
    final_answer_ready: bool = False
    next_action: str | None = None

    def __post_init__(self) -> None:
        if self.phase is not None:
            self.phase = _normalize_non_empty("runtime tool plan phase", self.phase)
        if not isinstance(self.known_refs, dict):
            raise ValidationError("runtime tool plan known_refs must be a dictionary.")
        normalized_refs: dict[str, str] = {}
        for raw_key, raw_value in self.known_refs.items():
            key = _normalize_non_empty("runtime tool plan ref key", str(raw_key))
            value = _normalize_non_empty("runtime tool plan ref value", str(raw_value))
            normalized_refs[key] = value
        self.known_refs = normalized_refs
        self.missing_outputs = _normalize_string_list("runtime tool plan missing_outputs", self.missing_outputs)
        self.next_allowed_tools = _normalize_string_list(
            "runtime tool plan next_allowed_tools",
            self.next_allowed_tools,
        )
        self.required_tools = _normalize_string_list(
            "runtime tool plan required_tools",
            self.required_tools,
        )
        self.discouraged_tools = _normalize_string_list(
            "runtime tool plan discouraged_tools",
            self.discouraged_tools,
        )
        self.schema_groups = _normalize_string_list("runtime tool plan schema_groups", self.schema_groups)
        if not isinstance(self.final_answer_ready, bool):
            raise ValidationError("runtime tool plan final_answer_ready must be a boolean.")
        if self.next_action is not None:
            self.next_action = _normalize_non_empty("runtime tool plan next_action", self.next_action)

    def is_empty(self) -> bool:
        return (
            self.phase is None
            and not self.known_refs
            and not self.missing_outputs
            and not self.next_allowed_tools
            and not self.required_tools
            and not self.discouraged_tools
            and not self.schema_groups
            and not self.final_answer_ready
            and self.next_action is None
        )


def build_runtime_tool_plan(
    *,
    workflow_phase: WorkflowPhaseSnapshot,
    career_flow_state: CareerFlowState,
    workflow_state: CurrentWorkflowState,
) -> RuntimeToolPlan:
    """Build a narrow next-tool plan for the current main-agent round."""

    if workflow_phase.is_empty() or workflow_phase.phase_name is None:
        return RuntimeToolPlan()

    phase = workflow_phase.phase_name
    known_refs = _known_refs(workflow_state=workflow_state, career_flow_state=career_flow_state)
    missing_outputs = [item.name for item in workflow_phase.missing_outputs]
    final_answer_ready = workflow_phase.final_answer_ready or (
        phase in _FINAL_WHEN_NO_MISSING_PHASES and not missing_outputs
    )
    if final_answer_ready:
        discouraged_tools = _final_discouraged_tools()
        if phase == "retrieval_read_only":
            discouraged_tools = _dedupe_strings([*discouraged_tools, *_retrieval_read_only_discouraged_tools()])
        return RuntimeToolPlan(
            phase=phase,
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=[],
            discouraged_tools=discouraged_tools,
            schema_groups=[],
            final_answer_ready=True,
            next_action="关键产物已完成；停止工具调用，直接面向用户总结结果和可预览资产。",
        )

    if phase == "resume_diagnosis":
        return _resume_diagnosis_plan(known_refs=known_refs, missing_outputs=missing_outputs)
    if phase == "jd_fit":
        return _jd_fit_plan(
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            input_refs=workflow_phase.input_refs,
        )
    if phase == "resume_version":
        return _resume_version_plan(known_refs=known_refs, missing_outputs=missing_outputs)
    if phase == "application_action":
        return _application_action_plan(
            known_refs=known_refs,
            career_flow_state=career_flow_state,
        )
    if phase == "retrieval_read_only":
        return _retrieval_read_only_plan(
            known_refs=known_refs,
            missing_outputs=missing_outputs,
        )
    action_contract = action_contract_for_phase(phase)
    if action_contract is not None:
        return _action_contract_runtime_plan(
            contract=action_contract,
            known_refs=known_refs,
            missing_outputs=missing_outputs,
        )

    return RuntimeToolPlan(
        phase=phase,
        known_refs=known_refs,
        missing_outputs=missing_outputs,
        final_answer_ready=False,
        next_action=workflow_phase.next_action_hint,
    )


def format_runtime_tool_plan_lines(plan: RuntimeToolPlan) -> list[str]:
    """Render the runtime tool plan as a compact model-facing section."""

    if plan.is_empty():
        return []
    lines: list[str] = []
    if plan.phase:
        lines.append(f"- phase={plan.phase}")
    if plan.known_refs:
        refs = ",".join(f"{key}={value}" for key, value in plan.known_refs.items())
        lines.append(f"- known_refs={refs}")
    if plan.missing_outputs:
        lines.append(f"- missing_outputs={','.join(plan.missing_outputs)}")
    if plan.next_allowed_tools:
        lines.append(f"- next_allowed_tools={','.join(plan.next_allowed_tools)}")
    if plan.required_tools:
        lines.append(f"- required_tools={','.join(plan.required_tools)}")
    if plan.discouraged_tools:
        lines.append(f"- discouraged_tools={','.join(plan.discouraged_tools)}")
    if plan.schema_groups:
        lines.append(f"- schema_groups={','.join(plan.schema_groups)}")
    lines.append(f"- final_answer_ready={str(plan.final_answer_ready).lower()}")
    if plan.next_action:
        lines.append(f"- next_action={plan.next_action}")
    return lines


def pending_runtime_plan_from_tool_search_result(content: str) -> dict[str, Any] | None:
    """Extract a pending runtime plan from a tool_search result."""

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    return _pending_plan_from_runtime_applied_payload(payload)


def _pending_plan_from_runtime_applied_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or payload.get("runtime_plan_applied") is not True:
        return None
    if payload.get("runtime_final_answer_ready") is True:
        return None
    next_allowed_tools = runtime_plan_next_allowed_tools(payload)
    if not next_allowed_tools:
        return None
    return {
        "phase": payload.get("runtime_plan_phase"),
        "next_action": payload.get("runtime_next_action"),
        "next_allowed_tools": next_allowed_tools,
        "required_tools": _runtime_plan_required_tools(
            {
                "required_tools": payload.get("required_tools"),
                "runtime_missing_outputs": payload.get("runtime_missing_outputs"),
                "next_allowed_tools": next_allowed_tools,
            }
        ),
        "known_refs": payload.get("runtime_known_refs") if isinstance(payload.get("runtime_known_refs"), dict) else {},
        "missing_outputs": payload.get("runtime_missing_outputs")
        if isinstance(payload.get("runtime_missing_outputs"), list)
        else [],
        "discouraged_tools": runtime_plan_discouraged_tools(payload),
    }


def merge_pending_runtime_plan(
    *,
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Keep the stricter runtime completion requirement across helper searches."""

    if current is None:
        return incoming
    if current.get("final_answer_ready") is True:
        return current
    if incoming.get("final_answer_ready") is True:
        return incoming
    if _is_completed_jd_fit_plan(current) and _is_regressive_jd_fit_plan(incoming):
        return current
    current_required = _runtime_plan_required_tools(current)
    incoming_required = _runtime_plan_required_tools(incoming)
    if current_required and not incoming_required:
        return current
    if current_required and incoming_required:
        merged = dict(incoming)
        if not merged.get("phase") and current.get("phase"):
            merged["phase"] = current.get("phase")
        merged["required_tools"] = _dedupe_strings([*current_required, *incoming_required])
        merged["missing_outputs"] = _dedupe_strings(
            [
                *[str(item) for item in current.get("missing_outputs", []) if str(item).strip()],
                *[str(item) for item in incoming.get("missing_outputs", []) if str(item).strip()],
            ]
        )
        merged["discouraged_tools"] = _dedupe_strings(
            [
                *runtime_plan_discouraged_tools(current),
                *runtime_plan_discouraged_tools(incoming),
            ]
        )
        known_refs: dict[str, Any] = {}
        raw_current_refs = current.get("known_refs")
        raw_incoming_refs = incoming.get("known_refs")
        if isinstance(raw_current_refs, dict):
            known_refs.update(raw_current_refs)
        if isinstance(raw_incoming_refs, dict):
            known_refs.update(raw_incoming_refs)
        merged["known_refs"] = known_refs
        _merge_plan_extra_payloads(merged, current=current, incoming=incoming)
        return merged
    return incoming


def _merge_plan_extra_payloads(
    target: dict[str, Any],
    *,
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> None:
    for key in ("report_artifact_contract",):
        raw_value = incoming.get(key)
        if not isinstance(raw_value, dict):
            raw_value = current.get(key)
        if isinstance(raw_value, dict):
            target[key] = raw_value


def pending_runtime_plan_from_context_bundle(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a pending runtime plan from the assembled context bundle."""

    if not isinstance(payload, dict):
        return None
    if payload.get("final_answer_ready") is True:
        return {
            "phase": payload.get("phase"),
            "next_action": payload.get("next_action"),
            "next_allowed_tools": [],
            "required_tools": [],
            "known_refs": payload.get("known_refs") if isinstance(payload.get("known_refs"), dict) else {},
            "missing_outputs": [],
            "discouraged_tools": runtime_plan_discouraged_tools(payload),
            "final_answer_ready": True,
        }
    next_allowed_tools = runtime_plan_next_allowed_tools(payload)
    required_tools = _runtime_plan_required_tools(payload)
    if not next_allowed_tools or not required_tools:
        return None
    return {
        "phase": payload.get("phase"),
        "next_action": payload.get("next_action"),
        "next_allowed_tools": next_allowed_tools,
        "required_tools": required_tools,
        "known_refs": payload.get("known_refs") if isinstance(payload.get("known_refs"), dict) else {},
        "missing_outputs": payload.get("missing_outputs") if isinstance(payload.get("missing_outputs"), list) else [],
        "discouraged_tools": runtime_plan_discouraged_tools(payload),
    }


def pending_runtime_plan_from_workflow_result(content: str) -> dict[str, Any] | None:
    """Extract a pending runtime plan from a workflow guard result."""

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("workflow_runtime_result") is not True:
        return None
    raw_missing_outputs = payload.get("missing_outputs") if isinstance(payload.get("missing_outputs"), list) else []
    raw_known_refs = payload.get("completed_refs")
    if not isinstance(raw_known_refs, dict):
        raw_known_refs = payload.get("known_refs") if isinstance(payload.get("known_refs"), dict) else {}
    if payload.get("terminal") is True and not raw_missing_outputs:
        return {
            "phase": payload.get("stage") or payload.get("phase"),
            "next_action": payload.get("next_action"),
            "next_allowed_tools": [],
            "required_tools": [],
            "known_refs": raw_known_refs,
            "missing_outputs": [],
            "discouraged_tools": runtime_plan_discouraged_tools(payload),
            "final_answer_ready": True,
        }
    if payload.get("policy") not in {"block", "reuse"}:
        return None
    next_allowed_tools = runtime_plan_next_allowed_tools(payload)
    if not next_allowed_tools:
        return None
    plan = {
        "phase": payload.get("stage") or payload.get("phase"),
        "next_action": payload.get("next_action"),
        "next_allowed_tools": next_allowed_tools,
        "required_tools": _runtime_plan_required_tools(payload),
        "known_refs": raw_known_refs,
        "missing_outputs": raw_missing_outputs,
        "discouraged_tools": runtime_plan_discouraged_tools(payload),
    }
    raw_contract = payload.get("report_artifact_contract")
    if isinstance(raw_contract, dict):
        plan["report_artifact_contract"] = raw_contract
    return plan


def pending_runtime_plan_from_successful_tool_result(
    tool_name: str,
    content: str,
    *,
    previous_pending_plan: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Infer a required follow-up plan after a successful workflow tool result."""

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None

    action_plan = _pending_action_plan_after_tool_result(
        tool_name,
        payload,
        previous_pending_plan=previous_pending_plan,
    )
    if action_plan is not None:
        return action_plan

    if tool_name == "delegate_agents":
        return _pending_plan_after_delegate_agents(payload, previous_pending_plan=previous_pending_plan)
    runtime_applied_plan = _pending_plan_from_runtime_applied_payload(payload)
    if runtime_applied_plan is not None:
        return runtime_applied_plan
    if tool_name == "career_resume_profile_save":
        return _pending_plan_after_resume_profile_save(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "session_create_text_artifact":
        return _pending_plan_after_text_artifact(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "career_jd_analysis_save":
        return _pending_plan_after_jd_analysis_save(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "career_job_fit_report_save":
        return _pending_plan_after_job_fit_report_save(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "career_application_get":
        return _pending_plan_after_application_get(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "career_application_merge":
        return _pending_plan_after_application_merge(payload, previous_pending_plan=previous_pending_plan)
    if tool_name == "retrieval_search":
        return _pending_plan_after_retrieval_search(previous_pending_plan=previous_pending_plan)
    if tool_name == "retrieval_context_pack":
        return _pending_plan_after_retrieval_context_pack(previous_pending_plan=previous_pending_plan)
    if tool_name != "career_resume_version_create":
        return None
    if payload.get("record_type") != "resume_version":
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(_runtime_known_refs_from_payload(payload))
    resume_version_id = known_refs.get("resume_version_id") or payload.get("record_id")
    if isinstance(resume_version_id, str) and resume_version_id.strip():
        known_refs["resume_version_id"] = resume_version_id.strip()
    if "application_id" not in known_refs and _can_create_application_from_resume_version_refs(known_refs):
        return _resume_version_application_create_plan(known_refs=known_refs)
    return {
        "phase": "resume_version",
        "next_action": "ResumeVersion 已创建；下一步只调用 career_application_merge，把该版本关联到当前求职项目。",
        "next_allowed_tools": ["career_application_merge"],
        "required_tools": ["career_application_merge"],
        "known_refs": known_refs,
        "missing_outputs": ["career_application_resume_version_link"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "career_resume_version_create",
            "career_application_list",
        ],
    }


def known_refs_from_successful_tool_result(tool_name: str, content: str) -> dict[str, Any]:
    """Extract durable workflow refs from any successful tool result."""

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}

    refs = _runtime_known_refs_from_payload(payload)
    record_id = payload.get("record_id")
    if isinstance(record_id, str) and record_id.strip():
        mapped_key = _TOOL_RECORD_ID_REF_KEYS.get(tool_name)
        if mapped_key is not None:
            refs[mapped_key] = record_id.strip()

    if tool_name == "session_read_artifact":
        artifact_id = _string_or_none(payload.get("artifact_id"))
        if artifact_id is not None:
            if artifact_id.startswith("artifact_jd"):
                refs.setdefault("source_artifact_id", artifact_id)
                refs.setdefault("jd_source_artifact_id", artifact_id)
            elif "resume" in artifact_id:
                refs.setdefault("resume_source_artifact_id", artifact_id)

    if tool_name == "session_create_text_artifact":
        artifact_id = _string_or_none(payload.get("artifact_id"))
        title = _string_or_none(payload.get("title")) or ""
        if artifact_id is not None and _looks_like_job_fit_report_artifact(title):
            refs["report_artifact_id"] = artifact_id
        elif artifact_id is not None and _looks_like_resume_diagnosis_artifact(title):
            refs["diagnosis_artifact_id"] = artifact_id
        elif artifact_id is not None and _looks_like_jd_source_artifact(title):
            refs["jd_source_artifact_id"] = artifact_id
        elif artifact_id is not None and _looks_like_resume_version_artifact(title):
            refs["resume_version_artifact_id"] = artifact_id

    source_artifact_id = _string_or_none(refs.get("source_artifact_id"))
    if source_artifact_id is not None:
        if tool_name in {"career_jd_analysis_get", "career_jd_analysis_save"}:
            refs.setdefault("jd_source_artifact_id", source_artifact_id)
        elif tool_name in {"career_resume_profile_get", "career_resume_profile_save"}:
            refs.setdefault("resume_source_artifact_id", source_artifact_id)
    return refs


def _pending_plan_after_application_merge(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload.get("record_type") != "career_application":
        return None
    if previous_pending_plan is None or previous_pending_plan.get("phase") != "resume_version":
        return None
    if "career_application_merge" not in runtime_plan_completion_tools(previous_pending_plan):
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(_runtime_known_refs_from_payload(payload))
    application_id = known_refs.get("application_id") or payload.get("record_id")
    if isinstance(application_id, str) and application_id.strip():
        known_refs["application_id"] = application_id.strip()
    return {
        "phase": "resume_version",
        "next_action": "定制简历已创建并合并进求职项目；停止工具调用，直接面向用户总结结果。",
        "next_allowed_tools": [],
        "required_tools": [],
        "known_refs": known_refs,
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": _final_discouraged_tools()
        + [
            "career_application_merge",
            "career_resume_version_create",
            "career_application_list",
            "career_resume_version_list",
        ],
    }


def _pending_plan_after_retrieval_search(
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if previous_pending_plan is None or previous_pending_plan.get("phase") != "retrieval_read_only":
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    missing_outputs = [
        item
        for item in _string_items(previous_pending_plan.get("missing_outputs"))
        if item != "retrieval_search"
    ]
    if "retrieval_context_pack" not in missing_outputs:
        return _retrieval_read_only_final_plan(known_refs=known_refs)
    return {
        "phase": "retrieval_read_only",
        "next_action": "retrieval_search 已完成；下一步只调用 retrieval_context_pack 组装上下文，随后直接回答。",
        "next_allowed_tools": ["retrieval_context_pack"],
        "required_tools": ["retrieval_context_pack"],
        "known_refs": known_refs,
        "missing_outputs": missing_outputs,
        "discouraged_tools": _dedupe_strings(
            [
                *_retrieval_read_only_discouraged_tools(),
                "retrieval_search",
                "career_application_get",
                "career_resume_profile_get",
                "career_jd_analysis_get",
                "career_job_fit_report_get",
                "note_get",
            ]
        ),
    }


def _pending_plan_after_retrieval_context_pack(
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if previous_pending_plan is None or previous_pending_plan.get("phase") != "retrieval_read_only":
        return None
    return _retrieval_read_only_final_plan(known_refs=_pending_known_refs(previous_pending_plan))


def _pending_plan_after_resume_profile_save(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload.get("record_type") != "resume_profile":
        return None
    known_refs = _runtime_known_refs_from_payload(payload)
    resume_profile_id = known_refs.get("resume_profile_id") or payload.get("record_id")
    if isinstance(resume_profile_id, str) and resume_profile_id.strip():
        known_refs["resume_profile_id"] = resume_profile_id.strip()

    previous_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(previous_refs)
    if previous_refs.get("diagnosis_artifact_id"):
        return _resume_diagnosis_final_plan(known_refs=known_refs)
    return None


def _pending_plan_after_text_artifact(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    raw_missing_outputs = (
        previous_pending_plan.get("missing_outputs") if previous_pending_plan is not None else None
    )
    title = payload.get("title")
    if not isinstance(title, str):
        return None
    artifact_id = payload.get("artifact_id")

    if (
        previous_pending_plan is not None
        and previous_pending_plan.get("phase") == "resume_diagnosis"
        and isinstance(raw_missing_outputs, list)
        and "diagnosis_artifact" in raw_missing_outputs
    ):
        if not _runtime_plan_expects_text_artifact(previous_pending_plan, "diagnosis_artifact") and not (
            _looks_like_resume_diagnosis_artifact(title)
        ):
            plan = dict(previous_pending_plan)
            plan["next_action"] = "刚创建的 artifact 不是简历诊断报告；仍需调用 session_create_text_artifact 生成简历诊断报告。"
            return plan

        known_refs = _pending_known_refs(previous_pending_plan)
        if isinstance(artifact_id, str) and artifact_id.strip():
            known_refs["diagnosis_artifact_id"] = artifact_id.strip()
        if "resume_profile" in raw_missing_outputs or "resume_profile_id" not in known_refs:
            return _resume_profile_save_plan(known_refs=known_refs)
        return _resume_diagnosis_final_plan(known_refs=known_refs)

    if (
        previous_pending_plan is not None
        and previous_pending_plan.get("phase") == "jd_fit"
        and isinstance(raw_missing_outputs, list)
        and "jd_source_artifact" in raw_missing_outputs
    ):
        if not _runtime_plan_expects_text_artifact(previous_pending_plan, "jd_source_artifact") and not (
            _looks_like_jd_source_artifact(title)
        ):
            plan = dict(previous_pending_plan)
            plan["next_action"] = "刚创建的 artifact 不是 JD 事实源；仍需调用 session_create_text_artifact 保存本轮 JD 文本。"
            return plan

        known_refs = _pending_known_refs(previous_pending_plan)
        if isinstance(artifact_id, str) and artifact_id.strip():
            known_refs["jd_source_artifact_id"] = artifact_id.strip()
        return _job_fit_delegate_plan(
            known_refs=known_refs,
            missing_outputs=[item for item in raw_missing_outputs if item != "jd_source_artifact"],
        )

    if (
        previous_pending_plan is not None
        and previous_pending_plan.get("phase") == "resume_version"
        and isinstance(raw_missing_outputs, list)
        and "resume_version" in raw_missing_outputs
    ):
        if not _runtime_plan_expects_text_artifact(previous_pending_plan, "resume_version") and not (
            _looks_like_resume_version_artifact(title)
        ):
            return None
        known_refs = _pending_known_refs(previous_pending_plan)
        if isinstance(artifact_id, str) and artifact_id.strip():
            known_refs["resume_version_artifact_id"] = artifact_id.strip()
        return _resume_version_create_plan(known_refs=known_refs)

    if not _runtime_plan_expects_text_artifact(previous_pending_plan, "job_fit_report_artifact") and not (
        _looks_like_job_fit_report_artifact(title)
    ):
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    if isinstance(artifact_id, str) and artifact_id.strip():
        known_refs["report_artifact_id"] = artifact_id.strip()
    if "jd_analysis_id" in known_refs:
        return _job_fit_report_save_plan(known_refs=known_refs)
    return _job_fit_jd_analysis_save_plan(known_refs=known_refs)


def _pending_plan_after_jd_analysis_save(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload.get("record_type") != "jd_analysis":
        return None
    raw_previous_refs = previous_pending_plan.get("known_refs") if previous_pending_plan is not None else None
    previous_refs: dict[str, Any] = raw_previous_refs if isinstance(raw_previous_refs, dict) else {}
    known_refs = dict(previous_refs)
    known_refs.update(_runtime_known_refs_from_payload(payload))
    jd_analysis_id = payload.get("record_id")
    if isinstance(jd_analysis_id, str) and jd_analysis_id.strip():
        known_refs["jd_analysis_id"] = jd_analysis_id.strip()

    if isinstance(known_refs.get("report_artifact_id"), str):
        return _job_fit_report_save_plan(known_refs=known_refs)

    if previous_pending_plan is not None:
        raw_missing_outputs = previous_pending_plan.get("missing_outputs")
        if isinstance(raw_missing_outputs, list) and "job_fit_report" not in raw_missing_outputs:
            return None
    return _job_fit_report_artifact_plan(known_refs=known_refs)


def _job_fit_report_artifact_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "JDAnalysis 已保存；下一步只调用 session_create_text_artifact 创建唯一的岗位匹配报告 artifact。",
        "next_allowed_tools": ["session_create_text_artifact"],
        "required_tools": ["session_create_text_artifact"],
        "known_refs": known_refs,
        "missing_outputs": ["job_fit_report_artifact", "job_fit_report"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "career_jd_analysis_save",
            "career_jd_analysis_get",
            "career_job_fit_report_save",
            "career_job_fit_report_get",
            "career_resume_profile_get",
            "career_profile_get",
        ],
    }


def _job_fit_jd_analysis_save_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "匹配报告 artifact 已创建；下一步只调用 career_jd_analysis_save 保存 JDAnalysis，然后保存 JobFitReport。",
        "next_allowed_tools": ["career_jd_analysis_save"],
        "required_tools": ["career_jd_analysis_save"],
        "known_refs": known_refs,
        "missing_outputs": ["jd_analysis", "job_fit_report"],
        "discouraged_tools": [
            "tool_search",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "career_jd_analysis_get",
            "career_job_fit_report_save",
            "career_job_fit_report_get",
            "career_resume_profile_get",
            "career_profile_get",
        ],
    }


def _job_fit_report_save_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "JDAnalysis 和匹配报告 artifact 已就绪；下一步只调用 career_job_fit_report_save，并引用已有 report_artifact_id。",
        "next_allowed_tools": ["career_job_fit_report_save"],
        "required_tools": ["career_job_fit_report_save"],
        "known_refs": known_refs,
        "missing_outputs": ["job_fit_report"],
        "discouraged_tools": [
            "tool_search",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "career_jd_analysis_save",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_resume_profile_get",
            "career_profile_get",
        ],
    }


def _job_fit_application_create_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "JDAnalysis 和 JobFitReport 已由子 agent 完成；下一步只调用 career_application_create 创建求职项目。",
        "next_allowed_tools": ["career_application_create"],
        "required_tools": ["career_application_create"],
        "known_refs": known_refs,
        "missing_outputs": ["career_application"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
            "career_resume_version_create",
        ],
    }


def _job_fit_final_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "JDAnalysis、JobFitReport 和匹配报告 artifact 已完成；停止工具调用，直接总结已保存的产品记录。",
        "next_allowed_tools": [],
        "required_tools": [],
        "known_refs": known_refs,
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "career_jd_analysis_save",
            "career_jd_analysis_get",
            "career_jd_analysis_list",
            "career_job_fit_report_save",
            "career_job_fit_report_get",
            "career_job_fit_report_list",
            "career_resume_profile_get",
            "career_profile_get",
        ],
    }


def _application_action_get_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "application_action",
        "next_action": "项目动作必须先读取当前 CareerApplication，确认已关联的 ResumeProfile、JDAnalysis、JobFitReport 和 ResumeVersion。",
        "next_allowed_tools": ["career_application_get"],
        "required_tools": ["career_application_get"],
        "known_refs": known_refs,
        "missing_outputs": ["career_application_read"],
        "discouraged_tools": [
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "retrieval_context_pack",
            "retrieval_search",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "career_resume_version_create",
            "career_application_list",
        ],
    }


def _application_action_merge_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "application_action",
        "next_action": "CareerApplication 已读取；围绕本次项目动作只调用 career_application_merge 更新 summary、next_actions、risks 或 notes。",
        "next_allowed_tools": ["career_application_merge"],
        "required_tools": ["career_application_merge"],
        "known_refs": known_refs,
        "missing_outputs": ["career_application_update"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "retrieval_context_pack",
            "retrieval_search",
            "career_application_get",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "career_resume_version_create",
        ],
    }


def _resume_diagnosis_final_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "resume_diagnosis",
        "next_action": "ResumeProfile 和简历诊断 artifact 已完成；停止工具调用，直接总结已保存的产品记录。",
        "next_allowed_tools": [],
        "required_tools": [],
        "known_refs": known_refs,
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "career_resume_profile_get",
            "career_resume_profile_save",
        ],
    }


def _resume_profile_save_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    diagnosis_artifact_id = known_refs.get("diagnosis_artifact_id")
    next_action = "简历诊断 artifact 已创建；下一步只调用 career_resume_profile_save 保存 ResumeProfile。"
    if isinstance(diagnosis_artifact_id, str) and diagnosis_artifact_id.strip():
        next_action = (
            "简历诊断 artifact 已创建；下一步只调用 career_resume_profile_save 保存 ResumeProfile，"
            f"并把 diagnosis_artifact_id 设置为 {diagnosis_artifact_id.strip()}。"
        )
    return {
        "phase": "resume_diagnosis",
        "next_action": next_action,
        "next_allowed_tools": ["career_resume_profile_save"],
        "required_tools": ["career_resume_profile_save"],
        "known_refs": known_refs,
        "missing_outputs": ["resume_profile"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "career_resume_profile_get",
        ],
    }


def _pending_known_refs(plan: dict[str, Any] | None) -> dict[str, Any]:
    if plan is None:
        return {}
    raw_refs = plan.get("known_refs")
    return dict(raw_refs) if isinstance(raw_refs, dict) else {}


def _runtime_plan_expects_text_artifact(plan: dict[str, Any] | None, missing_output: str) -> bool:
    if not isinstance(plan, dict):
        return False
    missing_outputs = {
        item.strip()
        for item in plan.get("missing_outputs", [])
        if isinstance(item, str) and item.strip()
    }
    if missing_output not in missing_outputs:
        return False
    return "session_create_text_artifact" in runtime_plan_completion_tools(plan)


def _pending_plan_after_job_fit_report_save(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload.get("record_type") != "job_fit_report":
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(_runtime_known_refs_from_payload(payload))
    fit_report_id = payload.get("record_id")
    if isinstance(fit_report_id, str) and fit_report_id.strip():
        known_refs["job_fit_report_id"] = fit_report_id.strip()
    if not known_refs.get("job_fit_report_id"):
        return None
    if previous_pending_plan is not None and previous_pending_plan.get("phase") not in {None, "jd_fit"}:
        return None
    return _job_fit_final_plan(known_refs=known_refs)


def _pending_plan_after_application_get(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if payload.get("record_type") != "career_application":
        return None
    if previous_pending_plan is None:
        return None
    if "career_application_get" not in runtime_plan_completion_tools(previous_pending_plan):
        return None
    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(_runtime_known_refs_from_payload(payload))
    application_id = known_refs.get("application_id") or payload.get("record_id")
    if isinstance(application_id, str) and application_id.strip():
        known_refs["application_id"] = application_id.strip()
    if previous_pending_plan.get("phase") == "resume_version":
        missing_outputs = [
            item
            for item in _string_items(previous_pending_plan.get("missing_outputs"))
            if item != "career_application_read"
        ]
        if "resume_version" in missing_outputs:
            return {
                "phase": "resume_version",
                "next_action": "CareerApplication 已读取；下一步只调用 career_resume_version_create 生成定制简历版本。",
                "next_allowed_tools": ["career_resume_version_create"],
                "required_tools": ["career_resume_version_create"],
                "known_refs": known_refs,
                "missing_outputs": missing_outputs,
                "discouraged_tools": [
                    "tool_search",
                    "delegate_agents",
                    "session_read_artifact",
                    "session_list_artifacts",
                    "career_application_get",
                    "career_application_list",
                    "career_application_merge",
                    "career_resume_profile_get",
                    "career_jd_analysis_get",
                    "career_job_fit_report_get",
                    "retrieval_search",
                    "retrieval_context_pack",
                ],
            }
    if previous_pending_plan.get("phase") != "application_action":
        return None
    return _application_action_merge_plan(known_refs=known_refs)


def _pending_plan_after_delegate_agents(
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    known_refs = _pending_known_refs(previous_pending_plan)
    known_refs.update(_delegate_result_known_refs(payload))
    phase = previous_pending_plan.get("phase") if previous_pending_plan is not None else None

    if (
        phase in {None, "jd_fit"}
        and "jd_analysis_id" in known_refs
        and "job_fit_report_id" in known_refs
        and "application_id" not in known_refs
    ):
        if previous_pending_plan is None or "career_application" in _string_items(
            previous_pending_plan.get("missing_outputs")
        ):
            return _job_fit_application_create_plan(known_refs=known_refs)
        return _job_fit_final_plan(known_refs=known_refs)

    if (
        phase == "resume_diagnosis"
        and "resume_profile_id" in known_refs
        and ("diagnosis_artifact_id" in known_refs or "report_artifact_id" in known_refs)
    ):
        if "diagnosis_artifact_id" not in known_refs and "report_artifact_id" in known_refs:
            known_refs["diagnosis_artifact_id"] = known_refs["report_artifact_id"]
        return _resume_diagnosis_final_plan(known_refs=known_refs)

    return None


def runtime_plan_next_allowed_tools(payload: dict[str, Any]) -> list[str]:
    raw_tools = payload.get("runtime_next_allowed_tools") or payload.get("next_allowed_tools")
    if not isinstance(raw_tools, list):
        return []
    return [item.strip() for item in raw_tools if isinstance(item, str) and item.strip()]


def runtime_plan_completion_tools(payload: dict[str, Any]) -> list[str]:
    required_tools = _runtime_plan_required_tools(payload)
    return required_tools or runtime_plan_next_allowed_tools(payload)


def runtime_plan_discouraged_tools(payload: dict[str, Any]) -> list[str]:
    raw_tools = (
        payload.get("runtime_discouraged_tools")
        or payload.get("discouraged_tools")
        or payload.get("blocked_tools")
        or payload.get("blocked_actions")
    )
    if not isinstance(raw_tools, list):
        return []
    return _dedupe_strings([item for item in raw_tools if isinstance(item, str)])


def _is_completed_jd_fit_plan(plan: dict[str, Any]) -> bool:
    if plan.get("phase") != "jd_fit":
        return False
    known_refs = _pending_known_refs(plan)
    if "job_fit_report_id" not in known_refs:
        return False
    return "jd_analysis_id" in known_refs or "report_artifact_id" in known_refs


def _is_regressive_jd_fit_plan(plan: dict[str, Any]) -> bool:
    if plan.get("phase") != "jd_fit":
        return False
    raw_missing_outputs = plan.get("missing_outputs")
    if not isinstance(raw_missing_outputs, list):
        return False
    missing_outputs = {item.strip() for item in raw_missing_outputs if isinstance(item, str) and item.strip()}
    return bool({"jd_analysis", "job_fit_report"} & missing_outputs)


def is_premature_runtime_plan_answer(
    *,
    pending_runtime_plan: dict[str, Any] | None,
    visible_tool_names: set[str],
) -> bool:
    if pending_runtime_plan is None:
        return False
    return any(tool_name in visible_tool_names for tool_name in runtime_plan_completion_tools(pending_runtime_plan))


def runtime_plan_notice(pending_runtime_plan: dict[str, Any] | None) -> str:
    if pending_runtime_plan is None:
        return "运行时守卫：当前流程还未完成，请先调用已揭示的下一步工具，不要直接最终答复。"
    next_allowed_tools = ", ".join(runtime_plan_next_allowed_tools(pending_runtime_plan))
    required_tools = ", ".join(runtime_plan_completion_tools(pending_runtime_plan))
    discouraged_tools = ", ".join(runtime_plan_discouraged_tools(pending_runtime_plan))
    missing_outputs = ", ".join(str(item) for item in pending_runtime_plan.get("missing_outputs") or [])
    raw_known_refs = pending_runtime_plan.get("known_refs")
    known_refs: dict[Any, Any] = raw_known_refs if isinstance(raw_known_refs, dict) else {}
    known_ref_text = ", ".join(f"{key}={value}" for key, value in known_refs.items())
    lines = [
        "运行时守卫：当前 workflow 还未完成，不能直接最终答复。",
        f"下一步只调用这些已揭示工具：{next_allowed_tools}。",
    ]
    if required_tools and required_tools != next_allowed_tools:
        lines.append(f"必须完成的产物工具：{required_tools}。")
    if discouraged_tools:
        lines.append(f"不要再调用这些工具：{discouraged_tools}。")
    if missing_outputs:
        lines.append(f"仍缺少产物：{missing_outputs}。")
    if known_ref_text:
        lines.append(f"已知引用：{known_ref_text}。")
    required_tool = runtime_plan_completion_tools(pending_runtime_plan)
    if len(required_tool) == 1:
        hint = build_required_tool_call_hint(required_tool[0], known_refs)
        if hint is not None:
            lines.append(f"下一次工具参数提示：{json.dumps(hint, ensure_ascii=False)}")
    next_action = pending_runtime_plan.get("next_action")
    if isinstance(next_action, str) and next_action.strip():
        lines.append(f"动作要求：{next_action.strip()}")
    return "\n".join(lines)


def workflow_incomplete_answer(pending_runtime_plan: dict[str, Any] | None) -> str:
    if pending_runtime_plan is None:
        return "当前 workflow 还有必需步骤未完成，已停止最终答复。"
    required_tools = ", ".join(runtime_plan_completion_tools(pending_runtime_plan)) or "未明确"
    missing_outputs = ", ".join(str(item) for item in pending_runtime_plan.get("missing_outputs") or []) or "未明确"
    next_action = pending_runtime_plan.get("next_action")
    if not isinstance(next_action, str) or not next_action.strip():
        next_action = "请先完成缺失产物，再生成最终答复。"
    return (
        "当前 workflow 还有必需步骤未完成，已停止最终答复。\n"
        f"缺失产物：{missing_outputs}\n"
        f"必须调用的工具：{required_tools}\n"
        f"下一步：{next_action.strip()}"
    )


def _resume_diagnosis_plan(*, known_refs: dict[str, str], missing_outputs: list[str]) -> RuntimeToolPlan:
    if "resume_profile" in missing_outputs:
        return RuntimeToolPlan(
            phase="resume_diagnosis",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["delegate_agents"],
            discouraged_tools=["session_read_artifact", "session_list_artifacts", "career_jd_analysis_save"],
            schema_groups=["delegation", "career_diagnosis"],
            next_action="委派 resume_agent 完成简历解析、诊断报告和 ResumeProfile；不要先手动读取简历全文。",
        )
    if "career_profile" in missing_outputs:
        return RuntimeToolPlan(
            phase="resume_diagnosis",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["career_resume_profile_get", "career_profile_merge"],
            discouraged_tools=["delegate_agents", "session_read_artifact", "session_list_artifacts"],
            schema_groups=["career_diagnosis"],
            next_action="ResumeProfile 已存在；只读取画像并 merge 职业画像，不要重复委派或重读 artifact。",
        )
    return RuntimeToolPlan(
        phase="resume_diagnosis",
        known_refs=known_refs,
        missing_outputs=missing_outputs,
        next_allowed_tools=[],
        discouraged_tools=_final_discouraged_tools(),
        final_answer_ready=True,
        next_action="简历诊断关键产物已完成；直接总结诊断结果。",
    )


def _jd_fit_plan(
    *,
    known_refs: dict[str, str],
    missing_outputs: list[str],
    input_refs: list[str] | None = None,
) -> RuntimeToolPlan:
    if "jd_analysis" in missing_outputs or "job_fit_report" in missing_outputs:
        if not _has_jd_source(known_refs=known_refs, input_refs=input_refs or []):
            return RuntimeToolPlan(
                phase="jd_fit",
                known_refs=known_refs,
                missing_outputs=_dedupe_strings(["jd_source_artifact", *missing_outputs]),
                next_allowed_tools=["session_create_text_artifact"],
                discouraged_tools=[
                    "delegate_agents",
                    "session_read_artifact",
                    "session_list_artifacts",
                    "career_resume_version_create",
                ],
                schema_groups=["session_artifacts", "career_jd_fit"],
                next_action=(
                    "本轮还没有可传给 job_agent 的 JD 事实源；先把用户提供的 JD 文本保存为 pasted_text artifact，"
                    "再委派 job_agent。"
                ),
            )
        return RuntimeToolPlan(
            phase="jd_fit",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["delegate_agents"],
            discouraged_tools=["session_read_artifact", "session_list_artifacts", "career_resume_version_create"],
            schema_groups=["delegation", "career_jd_fit"],
            next_action="委派 job_agent 完成 JDAnalysis 和 JobFitReport；不要在匹配报告前创建简历版本。",
        )
    if "career_application" in missing_outputs:
        return RuntimeToolPlan(
            phase="jd_fit",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["career_application_create"],
            discouraged_tools=[
                "delegate_agents",
                "session_read_artifact",
                "career_jd_analysis_get",
                "career_job_fit_report_get",
                "career_resume_version_create",
            ],
            schema_groups=["career_application"],
            next_action="JDAnalysis 和 JobFitReport 已存在；只创建 CareerApplication 串联本次求职项目。",
        )
    return RuntimeToolPlan(
        phase="jd_fit",
        known_refs=known_refs,
        missing_outputs=missing_outputs,
        next_allowed_tools=[],
        discouraged_tools=_final_discouraged_tools(),
        final_answer_ready=True,
        next_action="JD 匹配关键产物已完成；直接总结匹配结论和可预览报告。",
    )


def _job_fit_delegate_plan(*, known_refs: dict[str, Any], missing_outputs: list[Any]) -> dict[str, Any]:
    return {
        "phase": "jd_fit",
        "next_action": "JD 事实源 artifact 已创建；下一步委派 job_agent 完成 JDAnalysis 和 JobFitReport。",
        "next_allowed_tools": ["delegate_agents"],
        "required_tools": ["delegate_agents"],
        "known_refs": known_refs,
        "missing_outputs": _dedupe_strings([str(item) for item in missing_outputs if str(item).strip()])
        or ["jd_analysis", "job_fit_report", "career_application"],
        "discouraged_tools": [
            "tool_search",
            "session_create_text_artifact",
            "session_read_artifact",
            "session_list_artifacts",
            "career_resume_version_create",
        ],
    }


def _resume_version_create_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "resume_version",
        "next_action": "定制简历 artifact 已创建；下一步调用 career_resume_version_create 保存 ResumeVersion。",
        "next_allowed_tools": ["career_resume_version_create"],
        "required_tools": ["career_resume_version_create"],
        "known_refs": known_refs,
        "missing_outputs": ["resume_version"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_create_text_artifact",
            "session_read_artifact",
            "session_list_artifacts",
            "career_application_get",
            "career_application_list",
            "career_resume_profile_get",
            "career_jd_analysis_get",
            "career_job_fit_report_get",
        ],
    }


def _resume_version_application_create_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    refs = dict(known_refs)
    refs.setdefault("career_profile_id", "career_profile_default")
    return {
        "phase": "resume_version",
        "next_action": "ResumeVersion 已创建但缺少 CareerApplication；下一步调用 career_application_create 创建求职项目并关联该版本。",
        "next_allowed_tools": ["career_application_create"],
        "required_tools": ["career_application_create"],
        "known_refs": refs,
        "missing_outputs": ["career_application"],
        "discouraged_tools": [
            "tool_search",
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "career_resume_version_create",
            "career_application_list",
            "career_application_merge",
        ],
    }


def _can_create_application_from_resume_version_refs(known_refs: dict[str, Any]) -> bool:
    return all(
        isinstance(known_refs.get(key), str) and str(known_refs.get(key)).strip()
        for key in ("resume_profile_id", "jd_analysis_id", "job_fit_report_id")
    )


def _resume_version_plan(*, known_refs: dict[str, str], missing_outputs: list[str]) -> RuntimeToolPlan:
    required_refs = {"resume_profile_id", "jd_analysis_id", "job_fit_report_id", "application_id"}
    missing_refs = sorted(required_refs - set(known_refs))
    if "career_application_read" in missing_outputs and "application_id" in known_refs:
        return RuntimeToolPlan(
            phase="resume_version",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["career_application_get"],
            discouraged_tools=[
                "delegate_agents",
                "session_read_artifact",
                "session_list_artifacts",
                "career_application_list",
                "career_resume_version_create",
                "retrieval_search",
                "retrieval_context_pack",
            ],
            schema_groups=["career_application"],
            next_action="本次定制简历是基于现有求职项目的项目动作；先调用 career_application_get 读取项目，再生成 ResumeVersion。",
        )
    if missing_refs:
        can_create_application = (
            missing_refs == ["application_id"]
            and {"resume_profile_id", "jd_analysis_id", "job_fit_report_id"} <= set(known_refs)
        )
        if can_create_application:
            return RuntimeToolPlan(
                phase="resume_version",
                known_refs=known_refs,
                missing_outputs=_dedupe_strings([*missing_outputs, "career_application"]),
                next_allowed_tools=["career_application_create"],
                discouraged_tools=[
                    "delegate_agents",
                    "session_read_artifact",
                    "session_list_artifacts",
                    "career_application_list",
                    "career_resume_version_create",
                    "retrieval_search",
                    "retrieval_context_pack",
                ],
                schema_groups=["career_application"],
                next_action="当前缺少 CareerApplication，但简历画像、JDAnalysis 和匹配报告已齐；直接调用 career_application_create 创建求职项目，不要重新委派或列举旧项目。",
            )
        lookup_tool = "career_application_get" if "application_id" in known_refs else "career_application_list"
        return RuntimeToolPlan(
            phase="resume_version",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=[lookup_tool],
            discouraged_tools=["delegate_agents", "session_read_artifact", "retrieval_search"],
            schema_groups=["career_application"],
            next_action="定制简历缺少关键产品 id；优先从 CareerApplication 补齐，不要重新读取原始资料。",
        )
    if "resume_version" in missing_outputs:
        return RuntimeToolPlan(
            phase="resume_version",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["career_resume_version_create"],
            discouraged_tools=[
                "delegate_agents",
                "memory_write",
                "session_read_artifact",
                "session_list_artifacts",
                "career_application_get",
                "career_application_list",
                "career_resume_profile_get",
                "career_jd_analysis_get",
                "career_job_fit_report_get",
                "career_resume_version_list",
                "retrieval_search",
                "retrieval_context_pack",
            ],
            schema_groups=["career_resume_version"],
            next_action="关键产品 id 已齐；直接调用 career_resume_version_create 生成定制简历版本，不要再读取产品记录。",
        )
    if "career_application_resume_version_link" in missing_outputs:
        return RuntimeToolPlan(
            phase="resume_version",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["career_application_merge"],
            discouraged_tools=[
                "delegate_agents",
                "session_read_artifact",
                "career_resume_version_create",
                "career_application_list",
            ],
            schema_groups=["career_application"],
            next_action="ResumeVersion 已创建；只把 resume_version_id merge 回 CareerApplication。",
        )
    return RuntimeToolPlan(
        phase="resume_version",
        known_refs=known_refs,
        missing_outputs=missing_outputs,
        next_allowed_tools=[],
        discouraged_tools=_final_discouraged_tools(),
        final_answer_ready=True,
        next_action="定制简历产物已完成；直接答复用户并指向可预览版本。",
    )


def _application_action_plan(
    *,
    known_refs: dict[str, str],
    career_flow_state: CareerFlowState,
) -> RuntimeToolPlan:
    if "career_application_get" not in set(career_flow_state.do_not_repeat_tools):
        return RuntimeToolPlan(
            phase="application_action",
            known_refs=known_refs,
            missing_outputs=["career_application_read"],
            next_allowed_tools=["career_application_get"],
            discouraged_tools=[
                "delegate_agents",
                "session_read_artifact",
                "session_list_artifacts",
                "session_plan_artifact_access",
                "session_search_artifact",
                "session_create_text_artifact",
                "retrieval_context_pack",
                "retrieval_search",
                "career_resume_profile_save",
                "career_jd_analysis_save",
                "career_job_fit_report_save",
                "career_resume_version_create",
                "career_application_list",
            ],
            schema_groups=["career_application"],
            next_action="项目动作必须先读取当前 CareerApplication，再基于其中关联记录更新项目。",
        )
    return RuntimeToolPlan(
        phase="application_action",
        known_refs=known_refs,
        missing_outputs=["career_application_update"],
        next_allowed_tools=["career_application_merge"],
        discouraged_tools=[
            "delegate_agents",
            "session_read_artifact",
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_search_artifact",
            "session_create_text_artifact",
            "retrieval_context_pack",
            "retrieval_search",
            "career_application_get",
            "career_resume_profile_save",
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "career_resume_version_create",
        ],
        schema_groups=["career_application"],
        next_action="CareerApplication 已读取；只更新当前求职项目，不要重新解析简历或 JD。",
    )


def _retrieval_read_only_plan(*, known_refs: dict[str, str], missing_outputs: list[str]) -> RuntimeToolPlan:
    if "retrieval_search" in missing_outputs:
        return RuntimeToolPlan(
            phase="retrieval_read_only",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["retrieval_search"],
            required_tools=["retrieval_search"],
            discouraged_tools=_retrieval_read_only_discouraged_tools(),
            schema_groups=["retrieval"],
            next_action="本轮是只读召回；先调用 retrieval_search，不要执行任何写入或 career 产品更新工具。",
        )
    if "retrieval_context_pack" in missing_outputs:
        return RuntimeToolPlan(
            phase="retrieval_read_only",
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=["retrieval_context_pack"],
            required_tools=["retrieval_context_pack"],
            discouraged_tools=_retrieval_read_only_discouraged_tools()
            + [
                "retrieval_search",
                "career_application_get",
                "career_resume_profile_get",
                "career_jd_analysis_get",
                "career_job_fit_report_get",
                "note_get",
            ],
            schema_groups=["retrieval"],
            next_action="retrieval_search 已完成；下一步只调用 retrieval_context_pack 组装上下文，随后直接回答。",
        )
    return RuntimeToolPlan(
        phase="retrieval_read_only",
        known_refs=known_refs,
        missing_outputs=missing_outputs,
        next_allowed_tools=[],
        discouraged_tools=_final_discouraged_tools() + _retrieval_read_only_discouraged_tools(),
        final_answer_ready=True,
        next_action="只读召回上下文已完成；停止工具调用并直接回答用户。",
    )


def _retrieval_read_only_final_plan(*, known_refs: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "retrieval_read_only",
        "next_action": "只读召回上下文已完成；停止工具调用并直接回答用户。",
        "next_allowed_tools": [],
        "required_tools": [],
        "known_refs": known_refs,
        "missing_outputs": [],
        "final_answer_ready": True,
        "discouraged_tools": _dedupe_strings([*_final_discouraged_tools(), *_retrieval_read_only_discouraged_tools()]),
    }


def _action_contract_runtime_plan(
    *,
    contract: ActionContract,
    known_refs: dict[str, Any],
    missing_outputs: list[str],
) -> RuntimeToolPlan:
    payload = action_contract_plan_payload(
        contract=contract,
        known_refs=known_refs,
        missing_outputs=missing_outputs,
    )
    payload_phase = payload.get("phase")
    payload_known_refs = payload.get("known_refs")
    payload_missing_outputs = payload.get("missing_outputs")
    payload_next_allowed_tools = payload.get("next_allowed_tools")
    payload_required_tools = payload.get("required_tools")
    payload_discouraged_tools = payload.get("discouraged_tools")
    payload_schema_groups = payload.get("schema_groups")
    normalized_known_refs: dict[str, str] = {}
    if isinstance(payload_known_refs, dict):
        normalized_known_refs = {
            str(key): str(value)
            for key, value in payload_known_refs.items()
            if str(key).strip() and value is not None and str(value).strip()
        }
    normalized_missing_outputs = _string_items(payload_missing_outputs)
    normalized_next_allowed_tools = _string_items(payload_next_allowed_tools)
    normalized_required_tools = _string_items(payload_required_tools)
    normalized_discouraged_tools = _string_items(payload_discouraged_tools)
    normalized_schema_groups = _string_items(payload_schema_groups)
    return RuntimeToolPlan(
        phase=payload_phase if isinstance(payload_phase, str) else None,
        known_refs=normalized_known_refs,
        missing_outputs=normalized_missing_outputs,
        next_allowed_tools=normalized_next_allowed_tools,
        required_tools=normalized_required_tools,
        discouraged_tools=normalized_discouraged_tools,
        schema_groups=normalized_schema_groups,
        final_answer_ready=payload.get("final_answer_ready") is True,
        next_action=payload.get("next_action") if isinstance(payload.get("next_action"), str) else None,
    )


def _pending_action_plan_after_tool_result(
    tool_name: str,
    payload: dict[str, Any],
    *,
    previous_pending_plan: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return pending_action_plan_after_tool_result(
        tool_name,
        payload_known_refs=_runtime_known_refs_from_payload(payload),
        record_id=payload.get("record_id"),
        previous_pending_plan=previous_pending_plan,
        record_id_ref_key=_TOOL_RECORD_ID_REF_KEYS.get(tool_name),
    )


def _retrieval_read_only_discouraged_tools() -> list[str]:
    return [
        "memory_write",
        "note_create",
        "note_append",
        "learning_task_create",
        "career_application_create",
        "career_application_merge",
        "career_resume_version_create",
        "career_resume_profile_save",
        "career_profile_merge",
        "career_jd_analysis_save",
        "career_job_fit_report_save",
        "session_create_text_artifact",
        "delegate_agents",
    ]


def _known_refs(*, workflow_state: CurrentWorkflowState, career_flow_state: CareerFlowState) -> dict[str, str]:
    output = dict(workflow_state.refs)
    output.update(career_flow_state.refs)
    resume_version_ids = career_flow_state.multi_refs.get("resume_version_ids") or []
    if resume_version_ids:
        output["resume_version_id"] = resume_version_ids[-1]
    resume_version_artifact_ids = career_flow_state.multi_refs.get("resume_version_artifact_ids") or []
    if resume_version_artifact_ids:
        output["resume_version_artifact_id"] = resume_version_artifact_ids[-1]
    return {key: output[key] for key in _REF_KEY_ORDER if key in output}


def _final_discouraged_tools() -> list[str]:
    return [
        "tool_search",
        "delegate_agents",
        "session_read_artifact",
        "session_list_artifacts",
        "retrieval_search",
        "retrieval_context_pack",
        "career_resume_profile_get",
        "career_jd_analysis_get",
        "career_job_fit_report_get",
        "career_application_get",
        "career_resume_version_get",
    ]


def _runtime_known_refs_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for source in (payload, payload.get("record"), payload.get("ids")):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            if not isinstance(key, str) or value is None:
                continue
            if key.endswith("_id") or key.endswith("_ids") or key in {"record_id", "artifact_id"}:
                output.setdefault(key, value)
        for ref in _string_items(source.get("evidence_refs")):
            _apply_product_ref(output, ref)
        for ref in _string_items(source.get("product_refs")):
            _apply_product_ref(output, ref)
    return output


def _delegate_result_known_refs(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    if _delegate_payload_allows_structured_refs(payload):
        for ref in _string_items(payload.get("product_refs")):
            _apply_product_ref(output, ref)
        for ref in _string_items(payload.get("output_artifact_refs")) or _string_items(payload.get("artifact_refs")):
            _apply_artifact_ref(output, ref)
    results = payload.get("results")
    if isinstance(results, list):
        for result in results:
            if not isinstance(result, dict):
                continue
            if result.get("status") != "completed":
                continue
            for ref in _string_items(result.get("product_refs")):
                _apply_product_ref(output, ref)
            artifact_refs = _string_items(result.get("output_artifact_refs")) or _string_items(result.get("artifact_refs"))
            for ref in artifact_refs:
                _apply_artifact_ref(output, ref)
            for key in ("summary", "answer", "answer_preview"):
                text = result.get(key)
                if isinstance(text, str):
                    _apply_text_refs(output, text)
    return output


def _delegate_payload_allows_structured_refs(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        return True
    return status.strip() not in {"failed", "skipped"}


def _apply_product_ref(output: dict[str, Any], ref: str) -> None:
    if is_reserved_reference_value(ref):
        return
    if ref.startswith("resume_profile_"):
        output.setdefault("resume_profile_id", ref)
    elif ref == "career_profile_default" or ref.startswith("career_profile_"):
        output.setdefault("career_profile_id", ref)
    elif ref.startswith("jd_analysis_") or ref.startswith("jd_"):
        output.setdefault("jd_analysis_id", ref)
    elif ref.startswith("job_fit_report_") or ref.startswith("fit_"):
        output.setdefault("job_fit_report_id", ref)
    elif ref.startswith("application_"):
        output.setdefault("application_id", ref)
    elif ref.startswith("resume_version_"):
        output.setdefault("resume_version_id", ref)
    elif ref.startswith("note_"):
        output.setdefault("note_id", ref)
    elif ref.startswith("learning_task_"):
        output.setdefault("learning_task_id", ref)


def _apply_artifact_ref(output: dict[str, Any], ref: str) -> None:
    if ref.startswith("artifact_") and not is_reserved_reference_value(ref):
        output.setdefault("report_artifact_id", ref)


def _apply_text_refs(output: dict[str, Any], text: str) -> None:
    for match in _CONTROLLED_REF_RE.finditer(text):
        ref = match.group(0)
        if ref in _CONTROLLED_REF_FIELD_NAMES:
            continue
        if ref.startswith("artifact_"):
            _apply_artifact_ref(output, ref)
        else:
            _apply_product_ref(output, ref)


def _string_items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _runtime_plan_required_tools(payload: dict[str, Any]) -> list[str]:
    raw_tools = payload.get("required_tools")
    if isinstance(raw_tools, list):
        return [item.strip() for item in raw_tools if isinstance(item, str) and item.strip()]
    raw_missing_outputs = payload.get("runtime_missing_outputs") or payload.get("missing_outputs")
    if not isinstance(raw_missing_outputs, list):
        return []
    missing_outputs = {item.strip() for item in raw_missing_outputs if isinstance(item, str) and item.strip()}
    required: list[str] = []
    if "retrieval_search" in missing_outputs:
        required.append("retrieval_search")
    if "retrieval_context_pack" in missing_outputs:
        required.append("retrieval_context_pack")
    if "note" in missing_outputs:
        required.extend(["note_create", "note_append"])
    if "learning_task" in missing_outputs:
        required.append("learning_task_create")
    if "career_profile" in missing_outputs:
        required.append("career_profile_merge")
    if "career_application_read" in missing_outputs:
        required.append("career_application_get")
    if "career_application" in missing_outputs:
        required.append("career_application_create")
    if "resume_version" in missing_outputs:
        required.append("career_resume_version_create")
    if (
        "career_application_update" in missing_outputs
        or "career_application_merge" in missing_outputs
        or "career_application_resume_version_link" in missing_outputs
    ):
        required.append("career_application_merge")
    if "jd_source_artifact" in missing_outputs:
        required.append("session_create_text_artifact")
    if "jd_analysis" in missing_outputs or "job_fit_report" in missing_outputs:
        required.append("delegate_agents")
    next_allowed = set(runtime_plan_next_allowed_tools(payload))
    if next_allowed:
        required = [tool for tool in required if tool in next_allowed]
    return required


def _looks_like_resume_diagnosis_artifact(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if "resume_diagnosis" in normalized:
        return True
    if "resume" in compact and ("diagnosis" in compact or "profile" in compact) and "report" in compact:
        return True
    return "简历" in compact and ("诊断" in compact or "画像" in compact) and "报告" in compact


def _looks_like_job_fit_report_artifact(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if "匹配报告" in compact or "岗位匹配" in compact:
        return True
    if "匹配" in compact and "分析" in compact and "报告" in compact:
        return True
    return "jobfit" in compact and "report" in compact


def _looks_like_jd_source_artifact(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if _looks_like_job_fit_report_artifact(title):
        return False
    if "jd" in compact:
        return True
    if "岗位描述" in compact or "职位描述" in compact:
        return True
    return ("岗位" in compact or "职位" in compact) and ("要求" in compact or "目标" in compact)


def _looks_like_resume_version_artifact(title: str) -> bool:
    normalized = title.strip().casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if _looks_like_resume_diagnosis_artifact(title):
        return False
    if "简历版本" in compact or "定制简历" in compact:
        return True
    return "resume" in compact and "version" in compact


def _has_jd_source(*, known_refs: dict[str, str], input_refs: list[str]) -> bool:
    if known_refs.get("jd_source_artifact_id") or known_refs.get("jd_analysis_id"):
        return True
    resume_source_artifact_id = known_refs.get("resume_source_artifact_id")
    for ref in input_refs:
        if ref.startswith("artifact_") and ref != resume_source_artifact_id:
            return True
    return False


def _dedupe_strings(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw_item in items:
        item = raw_item.strip()
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


_REF_KEY_ORDER = [
    "application_id",
    "resume_source_artifact_id",
    "jd_source_artifact_id",
    "source_artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "report_artifact_id",
    "diagnosis_artifact_id",
    "resume_version_id",
    "resume_version_artifact_id",
    "note_id",
    "learning_task_id",
]

_TOOL_RECORD_ID_REF_KEYS = {
    "career_resume_profile_get": "resume_profile_id",
    "career_resume_profile_save": "resume_profile_id",
    "career_profile_get": "career_profile_id",
    "career_profile_merge": "career_profile_id",
    "career_jd_analysis_get": "jd_analysis_id",
    "career_jd_analysis_save": "jd_analysis_id",
    "career_job_fit_report_get": "job_fit_report_id",
    "career_job_fit_report_save": "job_fit_report_id",
    "career_application_get": "application_id",
    "career_application_create": "application_id",
    "career_application_merge": "application_id",
    "career_resume_version_get": "resume_version_id",
    "career_resume_version_create": "resume_version_id",
    "note_create": "note_id",
    "note_append": "note_id",
    "learning_task_create": "learning_task_id",
}

_CONTROLLED_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:"
    r"resume_profile_[A-Za-z0-9_-]+"
    r"|career_profile_default"
    r"|career_profile_[A-Za-z0-9_-]+"
    r"|jd_analysis_[A-Za-z0-9_-]+"
    r"|jd_[A-Za-z0-9_-]+"
    r"|job_fit_report_[A-Za-z0-9_-]+"
    r"|fit_[A-Za-z0-9_-]+"
    r"|application_[A-Za-z0-9_-]+"
    r"|resume_version_[A-Za-z0-9_-]+"
    r"|note_[A-Za-z0-9_-]+"
    r"|learning_task_[A-Za-z0-9_-]+"
    r"|artifact_[A-Za-z0-9_-]+"
    r")(?![A-Za-z0-9_])"
)

_CONTROLLED_REF_FIELD_NAMES = {
    "application_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "learning_task_id",
    "note_id",
    "resume_profile_id",
    "resume_version_id",
}


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_string_list(name: str, values: list[str]) -> list[str]:
    if not isinstance(values, list):
        raise ValidationError(f"{name} must be a list.")
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = _normalize_non_empty(name, str(raw))
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
