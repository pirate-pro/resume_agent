"""Short-term event extraction and formatting helpers."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.errors import ValidationError
from app.domain.models import EventRecord, RunContext
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AgentResultSummaryPayload,
    AgentTaskAssignedPayload,
)
from app.runtime.context_compactor import CONTEXT_SUMMARY_EVENT

_logger = logging.getLogger(__name__)
_CHILD_RESULT_SUMMARY_CHARS = 260
_OPTIONAL_PAYLOAD_ITEM_CHARS = 180
_KNOWN_REF_RE = re.compile(
    r"\b(?:artifact|resume_profile|career_profile|resume_version|application|fit|jd|jd_analysis|job_fit_report|task_group|task)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}\b"
)
_KNOWN_REF_FIELD_NAMES = {
    "artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "resume_version_id",
    "application_id",
    "fit_id",
    "jd_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "task_group_id",
    "task_id",
}


def latest_context_summaries(events: list[EventRecord], context: RunContext) -> list[EventRecord]:
    summaries = [
        event
        for event in events
        if event.type == CONTEXT_SUMMARY_EVENT
        and (event.agent_id == context.agent_id or context.agent_id == context.entry_agent_id)
    ]
    return summaries[-2:]


def exclude_context_summaries(events: list[EventRecord]) -> list[EventRecord]:
    return [event for event in events if event.type != CONTEXT_SUMMARY_EVENT]


def format_context_summary_lines(events: list[EventRecord]) -> list[str]:
    lines: list[str] = []
    for event in events:
        raw_summary = event.payload.get("summary") or event.payload.get("content")
        summary = str(raw_summary).strip() if raw_summary is not None else ""
        if not summary:
            continue
        compressed_count = event.payload.get("compressed_event_count")
        retained_count = event.payload.get("retained_event_count")
        lines.append(
            f"- ({event.event_id}) {summary} "
            f"[compressed_events={compressed_count}; retained_events={retained_count}]"
        )
    return lines


def extract_assigned_tasks(events: list[EventRecord], context: RunContext) -> list[AgentTaskAssignedPayload]:
    output: list[AgentTaskAssignedPayload] = []
    for event in events:
        if event.type != AGENT_TASK_ASSIGNED_EVENT:
            continue
        try:
            payload = AgentTaskAssignedPayload.from_payload(event.payload)
        except ValidationError as exc:
            _logger.warning("跳过非法 agent task 事件: event_id=%s error=%s", event.event_id, exc)
            continue
        if payload.target_agent_id != context.agent_id:
            continue
        if payload.child_run_id is not None and payload.child_run_id != context.run_id:
            continue
        output.append(payload)
    return output


def extract_child_result_summaries(
    events: list[EventRecord],
    context: RunContext,
) -> list[AgentResultSummaryPayload]:
    output: list[AgentResultSummaryPayload] = []
    for event in events:
        if event.type != AGENT_RESULT_SUMMARY_EVENT:
            continue
        try:
            payload = AgentResultSummaryPayload.from_payload(event.payload)
        except ValidationError as exc:
            _logger.warning("跳过非法 agent result summary 事件: event_id=%s error=%s", event.event_id, exc)
            continue
        if payload.target_agent_id != context.agent_id:
            continue
        output.append(payload)
    return output


def format_assigned_task_lines(tasks: list[AgentTaskAssignedPayload]) -> list[str]:
    lines: list[str] = []
    for task in tasks:
        extras = format_optional_payload_parts(
            [
                ("constraints", task.constraints),
                ("artifact_refs", task.artifact_refs),
            ]
        )
        suffix = f" [{'; '.join(extras)}]" if extras else ""
        lines.append(
            f"- task_id={task.task_id} from={task.source_agent_id} instruction={task.instruction}{suffix}"
        )
    return lines


def format_assigned_task_context_lines(tasks: list[AgentTaskAssignedPayload]) -> list[str]:
    lines: list[str] = []
    for task in tasks:
        if not task.task_context:
            continue
        payload = {
            "task_id": task.task_id,
            "target_agent_id": task.target_agent_id,
            "context": _bounded_context_value(task.task_context),
        }
        lines.append(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return lines


def format_child_result_summary_lines(results: list[AgentResultSummaryPayload]) -> list[str]:
    lines: list[str] = []
    for result in results:
        extras = format_optional_payload_parts(
            [
                ("next_steps", result.next_steps),
                ("artifact_refs", result.artifact_refs),
                ("output_artifact_refs", result.output_artifact_refs),
                ("product_refs", result.product_refs),
                ("summary_refs", _extract_known_refs(result.summary)),
                ("next_hint", _child_result_next_hints(result)),
            ]
        )
        suffix = f" [{'; '.join(extras)}]" if extras else ""
        lines.append(
            f"- task_id={result.task_id} agent={result.source_agent_id} status={result.status} "
            f"summary={_compact_summary_text(result.summary, max_chars=_CHILD_RESULT_SUMMARY_CHARS)}{suffix}"
        )
    return lines


def format_optional_payload_parts(parts: list[tuple[str, list[str]]]) -> list[str]:
    output: list[str] = []
    for label, values in parts:
        if not values:
            continue
        compact_values = [_truncate_inline(value, _OPTIONAL_PAYLOAD_ITEM_CHARS) for value in values[:8]]
        output.append(f"{label}: {', '.join(compact_values)}")
    return output


def _compact_summary_text(value: str, *, max_chars: int) -> str:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in value.splitlines():
        line = _strip_markdown_noise(raw_line)
        if not line or line in seen:
            continue
        lines.append(line)
        seen.add(line)
        if len(lines) >= 4:
            break
    text = "；".join(lines) if lines else value.strip()
    return _truncate_inline(text, max_chars)


def _strip_markdown_noise(value: str) -> str:
    line = value.strip()
    if not line:
        return ""
    if line.strip("-*_`| ") == "":
        return ""
    if re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?", line):
        return ""
    line = re.sub(r"^#{1,6}\s*", "", line)
    line = line.strip("*` ")
    return re.sub(r"\s+", " ", line)


def _extract_known_refs(value: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for match in _KNOWN_REF_RE.finditer(value):
        item = match.group(0)
        if item in _KNOWN_REF_FIELD_NAMES or item in seen:
            continue
        output.append(item)
        seen.add(item)
        if len(output) >= 12:
            break
    return output


def _child_result_next_hints(result: AgentResultSummaryPayload) -> list[str]:
    if result.status != "completed":
        return []
    if result.source_agent_id == "resume_agent":
        return [
            "use product_refs/resume_profile_id for career_profile_merge; if profile facts are missing, use career_resume_profile_get, not diagnosis artifact read"
        ]
    if result.source_agent_id == "job_agent":
        return [
            "use product_refs/output_artifact_refs for CareerApplication; if score is missing, use career_job_fit_report_get, not report artifact read"
        ]
    return []


def _truncate_inline(value: str, max_chars: int) -> str:
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return f"{text[: max_chars - 1]}…"


def is_other_agent_related_event(event: EventRecord, context: RunContext) -> bool:
    if event.agent_id == context.agent_id:
        return True
    if event.run_id == context.run_id:
        return True
    return event.parent_run_id == context.run_id


def _bounded_context_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 5:
        return _shorten_scalar(value)
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= 32:
                output["_truncated_keys"] = max(0, len(value) - 32)
                break
            output[str(raw_key)] = _bounded_context_value(raw_value, depth=depth + 1)
        return output
    if isinstance(value, list):
        items = [_bounded_context_value(item, depth=depth + 1) for item in value[:16]]
        if len(value) > 16:
            items.append({"_truncated_items": len(value) - 16})
        return items
    return _shorten_scalar(value)


def _shorten_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if len(text) <= 1200:
        return text
    return text[:1200].rstrip() + "...(truncated)"


def is_main_agent_orchestration_event(event: EventRecord, context: RunContext) -> bool:
    """Return whether an event belongs in the main-agent orchestration view."""
    if event.agent_id == context.agent_id:
        return True
    if event.type != AGENT_RESULT_SUMMARY_EVENT:
        return False
    try:
        payload = AgentResultSummaryPayload.from_payload(event.payload)
    except ValidationError as exc:
        _logger.warning("跳过非法 agent result summary 事件: event_id=%s error=%s", event.event_id, exc)
        return False
    return payload.target_agent_id == context.agent_id
