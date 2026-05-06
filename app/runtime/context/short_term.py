"""Short-term event extraction and formatting helpers."""

from __future__ import annotations

import logging

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


def format_child_result_summary_lines(results: list[AgentResultSummaryPayload]) -> list[str]:
    lines: list[str] = []
    for result in results:
        extras = format_optional_payload_parts(
            [
                ("next_steps", result.next_steps),
                ("artifact_refs", result.artifact_refs),
            ]
        )
        suffix = f" [{'; '.join(extras)}]" if extras else ""
        lines.append(
            f"- task_id={result.task_id} agent={result.source_agent_id} status={result.status} "
            f"summary={result.summary}{suffix}"
        )
    return lines


def format_optional_payload_parts(parts: list[tuple[str, list[str]]]) -> list[str]:
    output: list[str] = []
    for label, values in parts:
        if not values:
            continue
        output.append(f"{label}: {', '.join(values)}")
    return output


def is_other_agent_related_event(event: EventRecord, context: RunContext) -> bool:
    if event.agent_id == context.agent_id:
        return True
    if event.run_id == context.run_id:
        return True
    return event.parent_run_id == context.run_id
