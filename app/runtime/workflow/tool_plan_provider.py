"""Providers that derive RuntimeToolPlan from session facts."""

from __future__ import annotations

from collections.abc import Callable

from app.core.errors import StorageError, ValidationError
from app.domain.models import EventRecord, RunContext, SessionArtifact
from app.domain.protocols import SessionRepository
from app.runtime.context.career_flow_state import extract_career_flow_state
from app.runtime.context.short_term import is_main_agent_orchestration_event
from app.runtime.context.workflow_state import extract_current_workflow_state
from app.runtime.workflow.career_phase import build_career_phase_snapshot
from app.runtime.workflow.tool_plan import RuntimeToolPlan, build_runtime_tool_plan

__all__ = ["build_runtime_tool_plan_provider"]


def build_runtime_tool_plan_provider(
    *,
    session_repository: SessionRepository,
    active_artifact_limit: int = 5,
) -> Callable[[RunContext], RuntimeToolPlan | None]:
    """Create a runtime plan provider bound to the active session repository."""

    def provider(context: RunContext) -> RuntimeToolPlan | None:
        if context.agent_id != context.entry_agent_id:
            return None
        try:
            agent_events = session_repository.list_agent_events(context.session_id, context.agent_id)
            orchestration_events = session_repository.list_orchestration_events(context.session_id)
            visible_events = [
                event
                for event in _merge_context_events(agent_events, orchestration_events)
                if is_main_agent_orchestration_event(event, context)
            ]
            user_message = _latest_user_message(visible_events)
            if user_message is None:
                return None
            workflow_state = extract_current_workflow_state(visible_events, context)
            career_flow_state = extract_career_flow_state(
                visible_events,
                context,
                user_message=user_message,
                workflow_state=workflow_state,
            )
            workflow_phase = build_career_phase_snapshot(
                context=context,
                user_message=user_message,
                workflow_state=workflow_state,
                career_flow_state=career_flow_state,
                active_artifacts=_active_session_artifacts(
                    session_repository,
                    context.session_id,
                    limit=active_artifact_limit,
                ),
            )
            return build_runtime_tool_plan(
                workflow_phase=workflow_phase,
                career_flow_state=career_flow_state,
                workflow_state=workflow_state,
            )
        except (StorageError, ValidationError):
            return None

    return provider


def _merge_context_events(*event_groups: list[EventRecord]) -> list[EventRecord]:
    by_id: dict[str, EventRecord] = {}
    for group in event_groups:
        for event in group:
            by_id.setdefault(event.event_id, event)
    return sorted(by_id.values(), key=lambda item: (item.created_at, item.event_id))


def _latest_user_message(events: list[EventRecord]) -> str | None:
    for event in reversed(events):
        if event.type != "user_message":
            continue
        content = event.payload.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _active_session_artifacts(
    session_repository: SessionRepository,
    session_id: str,
    *,
    limit: int,
) -> list[SessionArtifact]:
    artifacts = session_repository.list_session_artifacts(session_id)
    active_ids = session_repository.get_active_artifact_ids(session_id)
    if not active_ids:
        return artifacts[-limit:]
    artifact_map = {item.artifact_id: item for item in artifacts}
    output: list[SessionArtifact] = []
    for artifact_id in active_ids:
        artifact = artifact_map.get(artifact_id)
        if artifact is not None:
            output.append(artifact)
        if len(output) >= limit:
            break
    return output
