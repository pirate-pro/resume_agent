"""Semantic career workflow state for main-agent orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import EventRecord, RunContext
from app.domain.reference_ids import is_reserved_reference_value
from app.runtime.agent_events import AGENT_RESULT_SUMMARY_EVENT
from app.runtime.context.models import CareerFlowState, CurrentWorkflowState

__all__ = [
    "extract_career_flow_state",
    "format_career_flow_state_lines",
]

_ID_PATTERN = re.compile(
    r"\b(?:artifact|resume_profile|career_profile|resume_version|application|fit|jd)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}\b"
)
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
]
_MULTI_REF_KEY_ORDER = ["resume_version_ids", "resume_version_artifact_ids"]
_COMPLETED_STEP_ORDER = [
    "resume_profile",
    "career_profile",
    "jd_analysis",
    "job_fit_report",
    "career_application",
    "resume_version",
]
_TOOL_REPEAT_ORDER = [
    "career_application_get",
    "career_resume_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_profile_get",
    "career_resume_version_get",
    "career_resume_version_create",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
]
_CURRENT_RUN_REPEAT_TOOLS = {
    "career_resume_profile_get",
    "career_jd_analysis_get",
    "career_job_fit_report_get",
    "career_profile_get",
    "career_resume_version_get",
    "career_application_get",
}


@dataclass(slots=True)
class _CareerFlowAccumulator:
    refs: dict[str, str] = field(default_factory=dict)
    multi_refs: dict[str, list[str]] = field(default_factory=dict)
    successful_tools: set[str] = field(default_factory=set)
    current_run_successful_tools: set[str] = field(default_factory=set)
    resume_version_created_current_run: bool = False
    application_merged_after_resume_version: bool = False


def extract_career_flow_state(
    events: list[EventRecord],
    context: RunContext,
    *,
    user_message: str,
    workflow_state: CurrentWorkflowState,
) -> CareerFlowState:
    """Build a compact semantic career state for the main agent."""

    if context.agent_id != context.entry_agent_id:
        return CareerFlowState()

    intent = _career_intent(user_message)
    accumulator = _CareerFlowAccumulator(refs=dict(workflow_state.refs))
    _seed_multi_refs_from_workflow_state(accumulator, workflow_state)

    for event in events:
        if event.type == "tool_result":
            _merge_tool_result(accumulator, event=event, context=context)
        elif event.type == AGENT_RESULT_SUMMARY_EVENT:
            _merge_agent_result_summary(accumulator, event.payload)

    if not intent and not accumulator.refs and not accumulator.multi_refs:
        return CareerFlowState()

    completed_steps = _completed_steps(accumulator)
    missing_steps = _missing_steps(intent=intent, completed_steps=completed_steps, refs=accumulator.refs)
    do_not_repeat_tools = _do_not_repeat_tools(accumulator)
    final_answer_ready = _final_answer_ready(intent=intent, accumulator=accumulator)
    next_action_hint = _next_action_hint(
        intent=intent,
        completed_steps=completed_steps,
        missing_steps=missing_steps,
        final_answer_ready=final_answer_ready,
        accumulator=accumulator,
    )
    refs = {key: accumulator.refs[key] for key in _REF_KEY_ORDER if key in accumulator.refs}
    multi_refs = {key: accumulator.multi_refs[key] for key in _MULTI_REF_KEY_ORDER if accumulator.multi_refs.get(key)}

    return CareerFlowState(
        refs=refs,
        multi_refs=multi_refs,
        completed_steps=completed_steps,
        missing_steps=missing_steps,
        do_not_repeat_tools=do_not_repeat_tools,
        next_action_hint=next_action_hint,
        final_answer_ready=final_answer_ready,
    )


def format_career_flow_state_lines(state: CareerFlowState) -> list[str]:
    """Render the state as a short model-facing section."""

    if state.is_empty():
        return []
    lines: list[str] = []
    for key in _REF_KEY_ORDER:
        value = state.refs.get(key)
        if value:
            lines.append(f"- {key}={value}")
    for key in _MULTI_REF_KEY_ORDER:
        values = state.multi_refs.get(key) or []
        if values:
            lines.append(f"- {key}={','.join(values[-5:])}")
    if state.completed_steps:
        lines.append(f"- completed={','.join(state.completed_steps)}")
    if state.missing_steps:
        lines.append(f"- missing={','.join(state.missing_steps)}")
    if "resume_version" in state.completed_steps or "resume_version" in state.missing_steps:
        lines.append(
            "- resume_version_fact_policy=Use ResumeProfile and resume source artifact as candidate facts. "
            "Use JDAnalysis/JobFitReport only to choose emphasis. Do not add candidate company, dates, "
            "projects, skills, quantified metrics, scores, percentages, latency, QPS, counts, or outcomes "
            "unless they are explicitly present in candidate facts."
        )
        lines.append(
            "- resume_version_retry_policy=If career_resume_version_create fails validation, retry that "
            "same tool with the invalid facts removed. Do not perform more get/list/read calls unless the "
            "error says a required id or artifact is missing."
        )
    lines.append(f"- final_answer_ready={str(state.final_answer_ready).lower()}")
    if state.next_action_hint:
        lines.append(f"- next_action={state.next_action_hint}")
    if state.do_not_repeat_tools:
        lines.append(f"- do_not_repeat={','.join(state.do_not_repeat_tools)}")
    return lines


def _seed_multi_refs_from_workflow_state(
    accumulator: _CareerFlowAccumulator,
    workflow_state: CurrentWorkflowState,
) -> None:
    resume_version_id = workflow_state.refs.get("resume_version_id")
    if resume_version_id:
        _add_multi_ref(accumulator, "resume_version_ids", resume_version_id)
    resume_version_artifact_id = workflow_state.refs.get("resume_version_artifact_id")
    if resume_version_artifact_id:
        _add_multi_ref(accumulator, "resume_version_artifact_ids", resume_version_artifact_id)


def _career_intent(user_message: str) -> set[str]:
    text = user_message.strip().casefold()
    intents: set[str] = set()
    application_action = _is_application_action_message(text)
    if application_action:
        intents.add("application_action")
        intents.add("career_application")
        return intents
    if _has_any(text, ("简历", "resume", "画像", "诊断")):
        intents.add("resume_profile")
    if _has_any(text, ("jd", "岗位", "职位", "岗位描述", "职位描述")):
        intents.add("jd_analysis")
    if _has_any(text, ("匹配", "适配", "匹配报告", "投递建议")):
        intents.add("job_fit_report")
    if _has_any(text, ("求职项目", "application_", "投递", "申请", "面试准备", "投递前")):
        intents.add("career_application")
    if _has_any(text, ("定制简历", "简历版本", "生成一版简历", "生成或更新一版定制简历")):
        intents.add("resume_version")
        intents.add("career_application")
    return intents


def _merge_tool_result(accumulator: _CareerFlowAccumulator, *, event: EventRecord, context: RunContext) -> None:
    payload = event.payload
    if payload.get("success") is not True:
        return
    tool_name = _optional_text(payload.get("tool_name"))
    content = payload.get("content")
    if not tool_name or not isinstance(content, str) or not _is_career_tool(tool_name):
        return
    decoded = _loads_json(content)
    if _is_runtime_block_payload(decoded):
        return
    accumulator.successful_tools.add(tool_name)
    if event.run_id == context.run_id:
        accumulator.current_run_successful_tools.add(tool_name)
    if tool_name == "delegate_agents":
        _merge_delegate_agents_result(accumulator, decoded)
        return
    _merge_value(accumulator, decoded if decoded is not None else content)

    if tool_name == "career_resume_version_create" and event.run_id == context.run_id:
        accumulator.resume_version_created_current_run = True
    elif (
        tool_name == "career_application_merge"
        and event.run_id == context.run_id
        and accumulator.resume_version_created_current_run
    ):
        accumulator.application_merged_after_resume_version = True


def _merge_delegate_agents_result(accumulator: _CareerFlowAccumulator, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    if _delegate_payload_allows_structured_refs(payload):
        _merge_structured_child_refs(accumulator, payload)
    results = payload.get("results")
    if not isinstance(results, list):
        return
    for result in results:
        if not isinstance(result, dict) or result.get("status") != "completed":
            continue
        _merge_structured_child_refs(accumulator, result)


def _merge_agent_result_summary(accumulator: _CareerFlowAccumulator, payload: Any) -> None:
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        return
    _merge_structured_child_refs(accumulator, payload)


def _merge_structured_child_refs(accumulator: _CareerFlowAccumulator, payload: dict[str, Any]) -> None:
    for ref in _string_items(payload.get("product_refs")):
        _merge_ref(accumulator, ref, record_type=None)

    artifact_key = _output_artifact_key_for_child(payload)
    if artifact_key is None:
        return
    for ref in _string_items(payload.get("output_artifact_refs")):
        _set_ref(accumulator, artifact_key, ref)


def _delegate_payload_allows_structured_refs(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if not isinstance(status, str) or not status.strip():
        return True
    return status.strip() not in {"failed", "skipped"}


def _output_artifact_key_for_child(payload: dict[str, Any]) -> str | None:
    agent_id = _optional_text(payload.get("target_agent_id")) or _optional_text(payload.get("source_agent_id"))
    if agent_id == "resume_agent":
        return "diagnosis_artifact_id"
    if agent_id == "job_agent":
        return "report_artifact_id"
    return None


def _merge_value(accumulator: _CareerFlowAccumulator, value: Any, *, record_type: str | None = None) -> None:
    if isinstance(value, dict):
        resolved_record_type = _optional_text(value.get("record_type")) or record_type
        record_id = _optional_text(value.get("record_id"))
        if record_id:
            _merge_ref(accumulator, record_id, record_type=resolved_record_type)

        record = value.get("record")
        if isinstance(record, dict):
            _merge_value(accumulator, record, record_type=resolved_record_type)

        records = value.get("records")
        if isinstance(records, list):
            for item in records[-8:]:
                _merge_value(accumulator, item, record_type=resolved_record_type)

        for raw_key, item in value.items():
            if isinstance(raw_key, str):
                _merge_key_value(
                    accumulator,
                    key=raw_key,
                    value=item,
                    record_type=resolved_record_type,
                )
            if isinstance(item, (dict, list)):
                _merge_value(accumulator, item, record_type=resolved_record_type)
            elif isinstance(item, str):
                _merge_text_refs(accumulator, item)
        return

    if isinstance(value, list):
        for item in value:
            _merge_value(accumulator, item, record_type=record_type)
        return

    if isinstance(value, str):
        _merge_text_refs(accumulator, value)


def _merge_key_value(
    accumulator: _CareerFlowAccumulator,
    *,
    key: str,
    value: Any,
    record_type: str | None,
) -> None:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                _merge_key_value(accumulator, key=key, value=item, record_type=record_type)
        return
    text = _optional_text(value)
    if text is None:
        return

    if key == "application_id":
        _set_ref(accumulator, "application_id", text)
    elif key in {"resume_profile_id", "base_resume_profile_id"}:
        _set_ref(accumulator, "resume_profile_id", text)
    elif key == "career_profile_id":
        _set_ref(accumulator, "career_profile_id", text)
    elif key in {"jd_analysis_id", "target_jd_analysis_id"}:
        _set_ref(accumulator, "jd_analysis_id", text)
    elif key == "job_fit_report_id":
        _set_ref(accumulator, "job_fit_report_id", text)
    elif key == "report_artifact_id":
        _set_ref(accumulator, "report_artifact_id", text)
    elif key == "diagnosis_artifact_id":
        _set_ref(accumulator, "diagnosis_artifact_id", text)
    elif key == "resume_version_id":
        _add_multi_ref(accumulator, "resume_version_ids", text)
    elif key == "resume_version_ids":
        _add_multi_ref(accumulator, "resume_version_ids", text)
    elif key in {"artifact_id", "source_artifact_id"} and record_type == "resume_version":
        _add_multi_ref(accumulator, "resume_version_artifact_ids", text)
    elif key == "source_artifact_id" and record_type in {"jd_analysis", "job_fit_report", "career_application"}:
        _set_ref(accumulator, "jd_source_artifact_id", text)
    elif key in {"source_artifact_id", "raw_text_artifact_id"} and record_type == "resume_profile":
        _set_ref(accumulator, "resume_source_artifact_id", text)
    else:
        _merge_text_refs(accumulator, text)


def _merge_ref(accumulator: _CareerFlowAccumulator, ref: str, *, record_type: str | None) -> None:
    if record_type == "career_application" or ref.startswith("application_"):
        _set_ref(accumulator, "application_id", ref)
    elif record_type == "resume_profile" or ref.startswith("resume_profile_"):
        _set_ref(accumulator, "resume_profile_id", ref)
    elif record_type == "career_profile" or ref.startswith("career_profile_"):
        _set_ref(accumulator, "career_profile_id", ref)
    elif record_type == "jd_analysis" or ref.startswith("jd_"):
        _set_ref(accumulator, "jd_analysis_id", ref)
    elif record_type == "job_fit_report" or ref.startswith("fit_"):
        _set_ref(accumulator, "job_fit_report_id", ref)
    elif record_type == "resume_version" or ref.startswith("resume_version_"):
        _add_multi_ref(accumulator, "resume_version_ids", ref)


def _merge_text_refs(accumulator: _CareerFlowAccumulator, text: str) -> None:
    for match in _ID_PATTERN.finditer(text):
        ref = match.group(0)
        _merge_ref(accumulator, ref, record_type=None)


def _set_ref(accumulator: _CareerFlowAccumulator, key: str, value: str) -> None:
    if _valid_ref_value(key, value):
        accumulator.refs[key] = value


def _add_multi_ref(accumulator: _CareerFlowAccumulator, key: str, value: str) -> None:
    if not _valid_multi_ref_value(key, value):
        return
    values = accumulator.multi_refs.setdefault(key, [])
    if value not in values:
        values.append(value)


def _completed_steps(accumulator: _CareerFlowAccumulator) -> list[str]:
    completed: list[str] = []
    if "resume_profile_id" in accumulator.refs:
        completed.append("resume_profile")
    if "career_profile_id" in accumulator.refs:
        completed.append("career_profile")
    if "jd_analysis_id" in accumulator.refs:
        completed.append("jd_analysis")
    if "job_fit_report_id" in accumulator.refs:
        completed.append("job_fit_report")
    if "application_id" in accumulator.refs:
        completed.append("career_application")
    if accumulator.multi_refs.get("resume_version_ids"):
        completed.append("resume_version")
    return [step for step in _COMPLETED_STEP_ORDER if step in completed]


def _missing_steps(*, intent: set[str], completed_steps: list[str], refs: dict[str, str]) -> list[str]:
    required: list[str] = []
    if "resume_profile" in intent:
        required.extend(["resume_profile", "career_profile"])
    if "jd_analysis" in intent:
        required.append("jd_analysis")
    if "job_fit_report" in intent:
        required.extend(["resume_profile", "career_profile", "jd_analysis", "job_fit_report"])
    if "career_application" in intent:
        required.append("career_application")
    if "resume_version" in intent:
        required.extend(["resume_profile", "jd_analysis", "job_fit_report", "career_application", "resume_version"])
    if "resume_version" in intent and "application_id" in refs:
        required = ["career_application", "resume_version"]
    completed = set(completed_steps)
    return [step for step in _COMPLETED_STEP_ORDER if step in set(required) and step not in completed]


def _do_not_repeat_tools(accumulator: _CareerFlowAccumulator) -> list[str]:
    tools: list[str] = []
    if "resume_profile_id" in accumulator.refs or "career_resume_profile_get" in accumulator.current_run_successful_tools:
        tools.append("career_resume_profile_get")
    if "jd_analysis_id" in accumulator.refs or "career_jd_analysis_get" in accumulator.current_run_successful_tools:
        tools.append("career_jd_analysis_get")
    if "job_fit_report_id" in accumulator.refs or "career_job_fit_report_get" in accumulator.current_run_successful_tools:
        tools.append("career_job_fit_report_get")
    if "career_profile_id" in accumulator.refs or "career_profile_get" in accumulator.current_run_successful_tools:
        tools.append("career_profile_get")
    if accumulator.multi_refs.get("resume_version_ids") or "career_resume_version_create" in accumulator.successful_tools:
        tools.append("career_resume_version_create")
    if "career_jd_analysis_save" in accumulator.successful_tools:
        tools.append("career_jd_analysis_save")
    if "career_job_fit_report_save" in accumulator.successful_tools:
        tools.append("career_job_fit_report_save")

    for tool_name in _CURRENT_RUN_REPEAT_TOOLS:
        if tool_name in accumulator.current_run_successful_tools:
            tools.append(tool_name)
    return [tool for tool in _TOOL_REPEAT_ORDER if tool in set(tools)]


def _final_answer_ready(*, intent: set[str], accumulator: _CareerFlowAccumulator) -> bool:
    if "resume_version" in intent:
        return accumulator.application_merged_after_resume_version
    return False


def _next_action_hint(
    *,
    intent: set[str],
    completed_steps: list[str],
    missing_steps: list[str],
    final_answer_ready: bool,
    accumulator: _CareerFlowAccumulator,
) -> str | None:
    if final_answer_ready:
        return "定制简历已创建并合并进求职项目，应直接给最终答复。"
    if "resume_version" in intent and "career_application" in completed_steps and "resume_version" not in completed_steps:
        return "已确认求职项目和关联记录，下一步只需创建 ResumeVersion 并合并 CareerApplication。"
    if "resume_version" in intent and "resume_version" in completed_steps and "career_application_merge" not in accumulator.current_run_successful_tools:
        return "已创建 ResumeVersion，下一步只需把 resume_version_id 合并进 CareerApplication。"
    if "job_fit_report" in intent and "job_fit_report" not in completed_steps:
        return "需要补齐 JDAnalysis 和 JobFitReport，再创建或更新 CareerApplication。"
    if "jd_analysis" in intent and "jd_analysis" not in completed_steps:
        return "需要基于 JD artifact 生成 JDAnalysis。"
    if "resume_profile" in intent and "resume_profile" not in completed_steps:
        return "需要基于简历 artifact 生成 ResumeProfile。"
    if missing_steps:
        return f"下一步补齐 {','.join(missing_steps)}。"
    if "career_application" in intent:
        return "围绕当前求职项目继续执行指定动作。"
    if intent:
        return "已确认当前求职流程状态；避免重复读取已确认记录。"
    return None


def _valid_ref_value(key: str, value: str) -> bool:
    prefix_by_key = {
        "application_id": "application_",
        "career_profile_id": "career_profile_",
        "diagnosis_artifact_id": "artifact_",
        "jd_analysis_id": "jd_",
        "jd_source_artifact_id": "artifact_",
        "job_fit_report_id": "fit_",
        "report_artifact_id": "artifact_",
        "resume_profile_id": "resume_profile_",
        "resume_source_artifact_id": "artifact_",
    }
    prefix = prefix_by_key.get(key)
    return prefix is not None and value.startswith(prefix) and not is_reserved_reference_value(value)


def _valid_multi_ref_value(key: str, value: str) -> bool:
    if key == "resume_version_ids":
        return value.startswith("resume_version_") and not is_reserved_reference_value(value)
    if key == "resume_version_artifact_ids":
        return value.startswith("artifact_") and not is_reserved_reference_value(value)
    return False


def _is_career_tool(tool_name: str) -> bool:
    return tool_name.startswith("career_") or tool_name == "delegate_agents"


def _loads_json(content: str) -> Any | None:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def _is_runtime_block_payload(payload: Any) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("workflow_runtime_result") is True
        and payload.get("policy") == "block"
        and payload.get("tool_executed") is False
    )


def _string_items(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _has_any(text: str, values: tuple[str, ...]) -> bool:
    return any(value in text for value in values)


def _is_application_action_message(text: str) -> bool:
    return _has_any(
        text,
        (
            "投递前检查",
            "面试准备",
            "申请进度",
            "项目动作",
            "pre_apply",
            "pre-apply",
            "interview prep",
        ),
    )
