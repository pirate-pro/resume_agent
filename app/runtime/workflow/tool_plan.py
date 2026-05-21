"""Runtime-facing next tool plan for career workflow rounds."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Any

from app.core.errors import ValidationError
from app.runtime.workflow.phase import WorkflowPhaseSnapshot

if TYPE_CHECKING:
    from app.runtime.context.models import CareerFlowState, CurrentWorkflowState

__all__ = [
    "RuntimeToolPlan",
    "build_runtime_tool_plan",
    "format_runtime_tool_plan_lines",
    "is_premature_runtime_plan_answer",
    "merge_pending_runtime_plan",
    "pending_runtime_plan_from_context_bundle",
    "pending_runtime_plan_from_successful_tool_result",
    "pending_runtime_plan_from_tool_search_result",
    "pending_runtime_plan_from_workflow_result",
    "runtime_plan_completion_tools",
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
        phase in {"resume_diagnosis", "jd_fit", "resume_version"} and not missing_outputs
    )
    if final_answer_ready:
        return RuntimeToolPlan(
            phase=phase,
            known_refs=known_refs,
            missing_outputs=missing_outputs,
            next_allowed_tools=[],
            discouraged_tools=_final_discouraged_tools(),
            schema_groups=[],
            final_answer_ready=True,
            next_action="关键产物已完成；停止工具调用，直接面向用户总结结果和可预览资产。",
        )

    if phase == "resume_diagnosis":
        return _resume_diagnosis_plan(known_refs=known_refs, missing_outputs=missing_outputs)
    if phase == "jd_fit":
        return _jd_fit_plan(known_refs=known_refs, missing_outputs=missing_outputs)
    if phase == "resume_version":
        return _resume_version_plan(known_refs=known_refs, missing_outputs=missing_outputs)

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
            {"missing_outputs": payload.get("runtime_missing_outputs"), "next_allowed_tools": next_allowed_tools}
        ),
        "known_refs": payload.get("runtime_known_refs") if isinstance(payload.get("runtime_known_refs"), dict) else {},
        "missing_outputs": payload.get("runtime_missing_outputs")
        if isinstance(payload.get("runtime_missing_outputs"), list)
        else [],
    }


def merge_pending_runtime_plan(
    *,
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Keep the stricter runtime completion requirement across helper searches."""

    if current is None:
        return incoming
    current_required = _runtime_plan_required_tools(current)
    incoming_required = _runtime_plan_required_tools(incoming)
    if current_required and not incoming_required:
        return current
    if current_required and incoming_required:
        merged = dict(incoming)
        merged["required_tools"] = _dedupe_strings([*current_required, *incoming_required])
        merged["missing_outputs"] = _dedupe_strings(
            [
                *[str(item) for item in current.get("missing_outputs", []) if str(item).strip()],
                *[str(item) for item in incoming.get("missing_outputs", []) if str(item).strip()],
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
        return merged
    return incoming


def pending_runtime_plan_from_context_bundle(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Extract a pending runtime plan from the assembled context bundle."""

    if not isinstance(payload, dict) or payload.get("final_answer_ready") is True:
        return None
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
    }


def pending_runtime_plan_from_workflow_result(content: str) -> dict[str, Any] | None:
    """Extract a pending runtime plan from a workflow guard block result."""

    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("workflow_runtime_result") is not True:
        return None
    if payload.get("terminal") is True or payload.get("policy") != "block":
        return None
    next_allowed_tools = runtime_plan_next_allowed_tools(payload)
    if not next_allowed_tools:
        return None
    raw_known_refs = payload.get("completed_refs")
    if not isinstance(raw_known_refs, dict):
        raw_known_refs = payload.get("known_refs") if isinstance(payload.get("known_refs"), dict) else {}
    return {
        "phase": payload.get("stage") or payload.get("phase"),
        "next_action": payload.get("next_action"),
        "next_allowed_tools": next_allowed_tools,
        "required_tools": _runtime_plan_required_tools(payload),
        "known_refs": raw_known_refs,
        "missing_outputs": payload.get("missing_outputs") if isinstance(payload.get("missing_outputs"), list) else [],
    }


def pending_runtime_plan_from_successful_tool_result(tool_name: str, content: str) -> dict[str, Any] | None:
    """Infer a required follow-up plan after a successful workflow tool result."""

    if tool_name != "career_resume_version_create":
        return None
    try:
        payload = json.loads(content)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("record_type") != "resume_version":
        return None
    known_refs = _runtime_known_refs_from_payload(payload)
    resume_version_id = known_refs.get("resume_version_id") or payload.get("record_id")
    if isinstance(resume_version_id, str) and resume_version_id.strip():
        known_refs["resume_version_id"] = resume_version_id.strip()
    return {
        "phase": "resume_version",
        "next_action": "ResumeVersion 已创建；下一步只调用 career_application_merge，把该版本关联到当前求职项目。",
        "next_allowed_tools": ["career_application_merge"],
        "required_tools": ["career_application_merge"],
        "known_refs": known_refs,
        "missing_outputs": ["career_application_resume_version_link"],
    }


def runtime_plan_next_allowed_tools(payload: dict[str, Any]) -> list[str]:
    raw_tools = payload.get("runtime_next_allowed_tools") or payload.get("next_allowed_tools")
    if not isinstance(raw_tools, list):
        return []
    return [item.strip() for item in raw_tools if isinstance(item, str) and item.strip()]


def runtime_plan_completion_tools(payload: dict[str, Any]) -> list[str]:
    required_tools = _runtime_plan_required_tools(payload)
    return required_tools or runtime_plan_next_allowed_tools(payload)


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
    if missing_outputs:
        lines.append(f"仍缺少产物：{missing_outputs}。")
    if known_ref_text:
        lines.append(f"已知引用：{known_ref_text}。")
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


def _jd_fit_plan(*, known_refs: dict[str, str], missing_outputs: list[str]) -> RuntimeToolPlan:
    if "jd_analysis" in missing_outputs or "job_fit_report" in missing_outputs:
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


def _resume_version_plan(*, known_refs: dict[str, str], missing_outputs: list[str]) -> RuntimeToolPlan:
    required_refs = {"resume_profile_id", "jd_analysis_id", "job_fit_report_id", "application_id"}
    missing_refs = sorted(required_refs - set(known_refs))
    if missing_refs:
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
            next_allowed_tools=[
                "career_application_get",
                "career_resume_profile_get",
                "career_jd_analysis_get",
                "career_job_fit_report_get",
                "career_resume_version_create",
            ],
            discouraged_tools=[
                "delegate_agents",
                "session_read_artifact",
                "career_resume_version_list",
                "retrieval_search",
                "retrieval_context_pack",
            ],
            schema_groups=["career_read", "career_resume_version"],
            next_action="关键产品 id 已齐；如需正文事实，只读取产品记录，然后调用 career_resume_version_create 生成定制简历版本。",
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
    return output


def _runtime_plan_required_tools(payload: dict[str, Any]) -> list[str]:
    raw_tools = payload.get("required_tools")
    if isinstance(raw_tools, list):
        return [item.strip() for item in raw_tools if isinstance(item, str) and item.strip()]
    raw_missing_outputs = payload.get("runtime_missing_outputs") or payload.get("missing_outputs")
    if not isinstance(raw_missing_outputs, list):
        return []
    missing_outputs = {item.strip() for item in raw_missing_outputs if isinstance(item, str) and item.strip()}
    required: list[str] = []
    if "career_profile" in missing_outputs:
        required.append("career_profile_merge")
    if "career_application" in missing_outputs:
        required.append("career_application_create")
    if "resume_version" in missing_outputs:
        required.append("career_resume_version_create")
    if "career_application_merge" in missing_outputs or "career_application_resume_version_link" in missing_outputs:
        required.append("career_application_merge")
    if "jd_analysis" in missing_outputs or "job_fit_report" in missing_outputs:
        required.append("delegate_agents")
    next_allowed = set(runtime_plan_next_allowed_tools(payload))
    if next_allowed:
        required = [tool for tool in required if tool in next_allowed]
    return required


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
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "report_artifact_id",
    "diagnosis_artifact_id",
    "resume_version_id",
    "resume_version_artifact_id",
]


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


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
