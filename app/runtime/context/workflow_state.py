"""Current workflow state extraction from short-term events."""

from __future__ import annotations

import json
import re
from typing import Any

from app.domain.models import EventRecord, RunContext
from app.domain.reference_ids import is_reserved_reference_value
from app.runtime.agent_events import AGENT_RESULT_SUMMARY_EVENT
from app.runtime.context.models import CurrentWorkflowState

__all__ = ["extract_current_workflow_state", "format_current_workflow_state_lines"]

_STATE_KEY_ORDER = [
    "resume_source_artifact_id",
    "jd_source_artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "report_artifact_id",
    "diagnosis_artifact_id",
    "application_id",
    "resume_version_id",
    "resume_version_artifact_id",
    "note_id",
    "learning_task_id",
    "learning_plan_id",
]
_STATE_KEY_SET = set(_STATE_KEY_ORDER)
_ID_PATTERN = re.compile(
    r"\b(?:artifact|resume_profile|career_profile|resume_version|application|fit|jd|note|learning_task|learning_plan|weakness)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}\b"
)
_RECORD_TYPE_TO_ID_KEY = {
    "career_application": "application_id",
    "career_profile": "career_profile_id",
    "jd_analysis": "jd_analysis_id",
    "job_fit_report": "job_fit_report_id",
    "learning_plan": "learning_plan_id",
    "learning_task": "learning_task_id",
    "note": "note_id",
    "resume_profile": "resume_profile_id",
    "resume_version": "resume_version_id",
}
_FIELD_TO_STATE_KEY = {
    "application_id": "application_id",
    "career_profile_id": "career_profile_id",
    "diagnosis_artifact_id": "diagnosis_artifact_id",
    "jd_analysis_id": "jd_analysis_id",
    "job_fit_report_id": "job_fit_report_id",
    "learning_plan_id": "learning_plan_id",
    "learning_task_id": "learning_task_id",
    "note_id": "note_id",
    "report_artifact_id": "report_artifact_id",
    "resume_profile_id": "resume_profile_id",
    "resume_version_id": "resume_version_id",
    "target_jd_analysis_id": "jd_analysis_id",
}


def extract_current_workflow_state(events: list[EventRecord], context: RunContext) -> CurrentWorkflowState:
    """Extract the latest product refs visible to the main agent."""

    if context.agent_id != context.entry_agent_id:
        return CurrentWorkflowState()
    refs: dict[str, str] = {}
    source_tools: dict[str, str] = {}
    for event in events:
        if event.type == "tool_result":
            _merge_tool_result_event(refs, source_tools, event)
        elif event.type == AGENT_RESULT_SUMMARY_EVENT:
            _merge_refs_from_value(refs, source_tools, event.payload, source_tool="child_agent_result")
    return CurrentWorkflowState(
        refs={key: refs[key] for key in _STATE_KEY_ORDER if key in refs},
        source_tools={key: source_tools[key] for key in _STATE_KEY_ORDER if key in source_tools},
    )


def format_current_workflow_state_lines(state: CurrentWorkflowState) -> list[str]:
    lines: list[str] = []
    for key in _STATE_KEY_ORDER:
        value = state.refs.get(key)
        if value is None:
            continue
        source = state.source_tools.get(key)
        suffix = f" via {source}" if source else ""
        lines.append(f"- {key}={value}{suffix}")
    return lines


def _merge_tool_result_event(
    refs: dict[str, str],
    source_tools: dict[str, str],
    event: EventRecord,
) -> None:
    payload = event.payload
    if payload.get("success") is not True:
        return
    tool_name = _optional_text(payload.get("tool_name"))
    content = payload.get("content")
    if not tool_name or not isinstance(content, str) or not content.strip():
        return
    if not _is_workflow_state_tool(tool_name):
        return
    decoded = _loads_json(content)
    if _is_runtime_block_payload(decoded):
        return
    if decoded is None:
        _merge_refs_from_value(refs, source_tools, content, source_tool=tool_name)
        return
    _merge_refs_from_payload(refs, source_tools, decoded, source_tool=tool_name)


def _merge_refs_from_payload(
    refs: dict[str, str],
    source_tools: dict[str, str],
    payload: Any,
    *,
    source_tool: str,
    record_type: str | None = None,
) -> None:
    if isinstance(payload, dict):
        resolved_record_type = _optional_text(payload.get("record_type")) or record_type
        record_id_key = _RECORD_TYPE_TO_ID_KEY.get(resolved_record_type or "")
        record_id = _optional_text(payload.get("record_id"))
        if record_id_key and record_id:
            _set_ref(refs, source_tools, record_id_key, record_id, source_tool=source_tool)

        record = payload.get("record")
        if isinstance(record, dict):
            _merge_refs_from_payload(
                refs,
                source_tools,
                record,
                source_tool=source_tool,
                record_type=resolved_record_type,
            )

        records = payload.get("records")
        if isinstance(records, list) and records:
            latest_record = next((item for item in reversed(records) if isinstance(item, dict)), None)
            if latest_record is not None:
                _merge_refs_from_payload(
                    refs,
                    source_tools,
                    latest_record,
                    source_tool=source_tool,
                    record_type=resolved_record_type,
                )

        for key, value in payload.items():
            if not isinstance(key, str):
                continue
            _merge_key_value(
                refs,
                source_tools,
                key=key,
                value=value,
                source_tool=source_tool,
                record_type=resolved_record_type,
            )
            if isinstance(value, (dict, list)):
                _merge_refs_from_payload(
                    refs,
                    source_tools,
                    value,
                    source_tool=source_tool,
                    record_type=resolved_record_type,
                )
            elif isinstance(value, str):
                _merge_refs_from_text(refs, source_tools, value, source_tool=source_tool)
        return

    if isinstance(payload, list):
        for item in payload:
            _merge_refs_from_payload(refs, source_tools, item, source_tool=source_tool, record_type=record_type)
        return

    if isinstance(payload, str):
        _merge_refs_from_text(refs, source_tools, payload, source_tool=source_tool)


def _merge_refs_from_value(
    refs: dict[str, str],
    source_tools: dict[str, str],
    value: Any,
    *,
    source_tool: str,
) -> None:
    _merge_refs_from_payload(refs, source_tools, value, source_tool=source_tool)


def _merge_key_value(
    refs: dict[str, str],
    source_tools: dict[str, str],
    *,
    key: str,
    value: Any,
    source_tool: str,
    record_type: str | None,
) -> None:
    if isinstance(value, list):
        values = [_optional_text(item) for item in value]
        for item in values:
            if item:
                _merge_key_value(
                    refs,
                    source_tools,
                    key=key,
                    value=item,
                    source_tool=source_tool,
                    record_type=record_type,
                )
        return
    text = _optional_text(value)
    if text is None:
        return

    state_key = _FIELD_TO_STATE_KEY.get(key)
    if state_key:
        _set_ref(refs, source_tools, state_key, text, source_tool=source_tool)
        return

    if key == "source_artifact_id":
        if record_type == "resume_profile":
            _set_ref(refs, source_tools, "resume_source_artifact_id", text, source_tool=source_tool)
        elif record_type in {"career_application", "jd_analysis", "job_fit_report"}:
            _set_ref(refs, source_tools, "jd_source_artifact_id", text, source_tool=source_tool)
        elif record_type == "resume_version":
            _set_ref(refs, source_tools, "resume_version_artifact_id", text, source_tool=source_tool)
        return

    if key == "artifact_id" and record_type == "resume_version":
        _set_ref(refs, source_tools, "resume_version_artifact_id", text, source_tool=source_tool)
        return

    if key == "raw_text_artifact_id" and record_type == "resume_profile":
        _set_ref(refs, source_tools, "resume_source_artifact_id", text, source_tool=source_tool)
        return

    if key == "base_resume_profile_id":
        refs.setdefault("resume_profile_id", text)
        source_tools.setdefault("resume_profile_id", source_tool)
        return

    _merge_refs_from_text(refs, source_tools, text, source_tool=source_tool)


def _merge_refs_from_text(
    refs: dict[str, str],
    source_tools: dict[str, str],
    text: str,
    *,
    source_tool: str,
) -> None:
    for match in _ID_PATTERN.finditer(text):
        ref = match.group(0)
        state_key = _state_key_for_ref(ref)
        if state_key is None:
            continue
        _set_ref(refs, source_tools, state_key, ref, source_tool=source_tool, override=False)


def _state_key_for_ref(ref: str) -> str | None:
    if ref.startswith("resume_profile_"):
        return "resume_profile_id"
    if ref.startswith("career_profile_"):
        return "career_profile_id"
    if ref.startswith("resume_version_"):
        return "resume_version_id"
    if ref.startswith("application_"):
        return "application_id"
    if ref.startswith("fit_"):
        return "job_fit_report_id"
    if ref.startswith("jd_"):
        return "jd_analysis_id"
    if ref.startswith("note_"):
        return "note_id"
    if ref.startswith("learning_task_"):
        return "learning_task_id"
    if ref.startswith("learning_plan_"):
        return "learning_plan_id"
    return None


def _set_ref(
    refs: dict[str, str],
    source_tools: dict[str, str],
    key: str,
    value: str,
    *,
    source_tool: str,
    override: bool = True,
) -> None:
    if key not in _STATE_KEY_SET or not _is_valid_state_value(key, value):
        return
    if not override and key in refs:
        return
    refs[key] = value
    source_tools[key] = source_tool


def _is_workflow_state_tool(tool_name: str) -> bool:
    return tool_name.startswith(("career_", "note_", "learning_")) or tool_name in {
        "agent_task_status",
        "delegate_agents",
    }


def _is_valid_state_value(key: str, value: str) -> bool:
    prefix_by_key = {
        "application_id": "application_",
        "career_profile_id": "career_profile_",
        "diagnosis_artifact_id": "artifact_",
        "jd_analysis_id": "jd_",
        "jd_source_artifact_id": "artifact_",
        "job_fit_report_id": "fit_",
        "learning_plan_id": "learning_plan_",
        "learning_task_id": "learning_task_",
        "note_id": "note_",
        "report_artifact_id": "artifact_",
        "resume_profile_id": "resume_profile_",
        "resume_source_artifact_id": "artifact_",
        "resume_version_artifact_id": "artifact_",
        "resume_version_id": "resume_version_",
    }
    prefix = prefix_by_key.get(key)
    return prefix is not None and value.startswith(prefix) and not is_reserved_reference_value(value)


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


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None
