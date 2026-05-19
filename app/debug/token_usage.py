"""Token usage aggregation for the debug/management surface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from app.core.errors import SessionNotFoundError, ValidationError
from app.domain.models import EventRecord, SessionMeta
from app.domain.protocols import SessionRepository

__all__ = [
    "TokenUsageBucket",
    "TokenUsageCall",
    "TokenUsageContextSection",
    "TokenUsageDebugService",
    "TokenUsageSessionDetail",
    "TokenUsageSessionSummary",
    "TokenUsageSummary",
]


@dataclass(frozen=True, slots=True)
class TokenUsageContextSection:
    name: str
    tokens: int
    chars: int
    item_count: int
    pack_names: list[str]
    selection_mode: str | None


@dataclass(frozen=True, slots=True)
class TokenUsageCall:
    event_id: str
    session_id: str
    session_title: str
    agent_id: str
    run_id: str
    parent_run_id: str | None
    api: str
    operation: str
    mode: str
    phase: str
    round_index: int | None
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated: bool
    usage_source: str
    message_count: int
    tool_schema_count: int
    prompt_estimate_total_tokens: int
    system_prompt_estimate_tokens: int
    system_prompt_section_count: int
    system_prompt_sections: list[TokenUsageContextSection]
    messages_estimate_tokens: int
    tools_estimate_tokens: int
    message_user_estimate_tokens: int
    message_assistant_estimate_tokens: int
    message_tool_estimate_tokens: int
    message_other_estimate_tokens: int
    returned_tool_call_count: int
    content_chars: int
    reasoning_chars: int
    tool_context_window_mode: str
    pending_tool_exchange_count: int
    pending_tool_message_count: int
    compacted_tool_observation_count: int
    tool_state_message_estimate_tokens: int
    tool_pending_message_estimate_tokens: int
    workflow_rule_selection_mode: str
    workflow_rule_pack_names: list[str]
    workflow_rules_estimate_tokens: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class TokenUsageBucket:
    key: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int


@dataclass(frozen=True, slots=True)
class TokenUsageSessionSummary:
    session_id: str
    title: str
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int
    first_usage_at: datetime | None
    last_usage_at: datetime | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class TokenUsageSummary:
    session_count: int
    call_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_count: int
    provider_count: int
    agent_buckets: list[TokenUsageBucket]
    phase_buckets: list[TokenUsageBucket]
    model_buckets: list[TokenUsageBucket]
    sessions: list[TokenUsageSessionSummary]
    recent_calls: list[TokenUsageCall]


@dataclass(frozen=True, slots=True)
class TokenUsageSessionDetail:
    session: TokenUsageSessionSummary
    agent_buckets: list[TokenUsageBucket]
    phase_buckets: list[TokenUsageBucket]
    model_buckets: list[TokenUsageBucket]
    calls: list[TokenUsageCall]


@dataclass(slots=True)
class _Totals:
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_count: int = 0
    provider_count: int = 0
    first_usage_at: datetime | None = None
    last_usage_at: datetime | None = None

    def add(self, call: TokenUsageCall) -> None:
        self.call_count += 1
        self.prompt_tokens += call.prompt_tokens
        self.completion_tokens += call.completion_tokens
        self.total_tokens += call.total_tokens
        if call.estimated:
            self.estimated_count += 1
        else:
            self.provider_count += 1
        if self.first_usage_at is None or call.created_at < self.first_usage_at:
            self.first_usage_at = call.created_at
        if self.last_usage_at is None or call.created_at > self.last_usage_at:
            self.last_usage_at = call.created_at


class TokenUsageDebugService:
    """Read-only debug service backed by llm_usage session events."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def list_calls(
        self,
        *,
        session_id: str | None = None,
        agent_id: str | None = None,
        phase: str | None = None,
        estimated: bool | None = None,
        limit: int = 100,
    ) -> list[TokenUsageCall]:
        normalized_limit = _validate_limit("limit", limit, maximum=500)
        calls = self._filter_calls(
            self._collect_calls(session_id=session_id),
            agent_id=agent_id,
            phase=phase,
            estimated=estimated,
        )
        calls.sort(key=lambda item: item.created_at, reverse=True)
        return calls[:normalized_limit]

    def summarize(
        self,
        *,
        agent_id: str | None = None,
        phase: str | None = None,
        estimated: bool | None = None,
        session_limit: int = 10,
        call_limit: int = 10,
        bucket_limit: int = 8,
    ) -> TokenUsageSummary:
        normalized_session_limit = _validate_limit(
            "session_limit",
            session_limit,
            maximum=100,
        )
        normalized_call_limit = _validate_limit("call_limit", call_limit, maximum=100)
        normalized_bucket_limit = _validate_limit(
            "bucket_limit",
            bucket_limit,
            maximum=50,
        )
        calls = self._filter_calls(
            self._collect_calls(),
            agent_id=agent_id,
            phase=phase,
            estimated=estimated,
        )
        calls.sort(key=lambda item: item.created_at, reverse=True)
        totals = _summarize_calls(calls)
        sessions = self._build_session_summaries(calls)
        return TokenUsageSummary(
            session_count=len(sessions),
            call_count=totals.call_count,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            total_tokens=totals.total_tokens,
            estimated_count=totals.estimated_count,
            provider_count=totals.provider_count,
            agent_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.agent_id,
                limit=normalized_bucket_limit,
            ),
            phase_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.phase or "unknown",
                limit=normalized_bucket_limit,
            ),
            model_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.model or "unknown",
                limit=normalized_bucket_limit,
            ),
            sessions=sessions[:normalized_session_limit],
            recent_calls=calls[:normalized_call_limit],
        )

    def get_session_detail(
        self,
        session_id: str,
        *,
        limit: int = 200,
    ) -> TokenUsageSessionDetail:
        normalized_session_id = _normalize_required("session_id", session_id)
        normalized_limit = _validate_limit("limit", limit, maximum=1000)
        session = self._get_session_or_error(normalized_session_id)
        calls = self._collect_calls(session_id=normalized_session_id)
        calls.sort(key=lambda item: item.created_at, reverse=True)
        summary = self._build_session_summary(session, calls)
        limited_calls = calls[:normalized_limit]
        return TokenUsageSessionDetail(
            session=summary,
            agent_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.agent_id,
                limit=20,
            ),
            phase_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.phase or "unknown",
                limit=20,
            ),
            model_buckets=_bucketize(
                calls,
                key_getter=lambda item: item.model or "unknown",
                limit=20,
            ),
            calls=limited_calls,
        )

    def _collect_calls(self, *, session_id: str | None = None) -> list[TokenUsageCall]:
        sessions = self._target_sessions(session_id=session_id)
        calls: list[TokenUsageCall] = []
        for session in sessions:
            for event in self._session_repository.list_events(session.session_id):
                if event.type != "llm_usage":
                    continue
                calls.append(_call_from_event(session, event))
        return calls

    def _target_sessions(self, *, session_id: str | None) -> list[SessionMeta]:
        if session_id is None:
            return self._session_repository.list_sessions()
        normalized = _normalize_required("session_id", session_id)
        return [self._get_session_or_error(normalized)]

    def _get_session_or_error(self, session_id: str) -> SessionMeta:
        session = self._session_repository.get_session(session_id)
        if session is None:
            raise SessionNotFoundError(f"Session not found: {session_id}")
        return session

    def _filter_calls(
        self,
        calls: list[TokenUsageCall],
        *,
        agent_id: str | None,
        phase: str | None,
        estimated: bool | None,
    ) -> list[TokenUsageCall]:
        normalized_agent_id = _normalize_optional(agent_id)
        normalized_phase = _normalize_optional(phase)
        result: list[TokenUsageCall] = []
        for call in calls:
            if normalized_agent_id is not None and call.agent_id != normalized_agent_id:
                continue
            if normalized_phase is not None and call.phase != normalized_phase:
                continue
            if estimated is not None and call.estimated != estimated:
                continue
            result.append(call)
        return result

    def _build_session_summaries(
        self,
        calls: list[TokenUsageCall],
    ) -> list[TokenUsageSessionSummary]:
        calls_by_session: dict[str, list[TokenUsageCall]] = {}
        for call in calls:
            calls_by_session.setdefault(call.session_id, []).append(call)
        summaries: list[TokenUsageSessionSummary] = []
        for session_id, session_calls in calls_by_session.items():
            session = self._session_repository.get_session(session_id)
            if session is None:
                continue
            summaries.append(self._build_session_summary(session, session_calls))
        summaries.sort(
            key=lambda item: (
                item.last_usage_at or item.updated_at,
                item.updated_at,
            ),
            reverse=True,
        )
        return summaries

    def _build_session_summary(
        self,
        session: SessionMeta,
        calls: list[TokenUsageCall],
    ) -> TokenUsageSessionSummary:
        totals = _summarize_calls(calls)
        return TokenUsageSessionSummary(
            session_id=session.session_id,
            title=session.title,
            call_count=totals.call_count,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            total_tokens=totals.total_tokens,
            estimated_count=totals.estimated_count,
            provider_count=totals.provider_count,
            first_usage_at=totals.first_usage_at,
            last_usage_at=totals.last_usage_at,
            updated_at=session.updated_at,
        )


def _call_from_event(session: SessionMeta, event: EventRecord) -> TokenUsageCall:
    payload = event.payload
    prompt_tokens = _read_int(payload.get("prompt_tokens"))
    completion_tokens = _read_int(payload.get("completion_tokens"))
    total_tokens = _read_optional_int(payload.get("total_tokens"))
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    return TokenUsageCall(
        event_id=event.event_id,
        session_id=session.session_id,
        session_title=session.title,
        agent_id=event.agent_id,
        run_id=event.run_id,
        parent_run_id=event.parent_run_id,
        api=_read_str(payload.get("api"), default="POST /v1/chat/completions"),
        operation=_read_str(payload.get("operation")),
        mode=_read_str(payload.get("mode")),
        phase=_read_str(payload.get("phase")),
        round_index=_read_optional_int(payload.get("round_index")),
        model=_read_str(payload.get("model"), default="unknown"),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        estimated=payload.get("estimated") is True,
        usage_source=_read_str(payload.get("usage_source"), default="provider"),
        message_count=_read_int(payload.get("message_count")),
        tool_schema_count=_read_int(payload.get("tool_schema_count")),
        prompt_estimate_total_tokens=_read_int(payload.get("prompt_estimate_total_tokens")),
        system_prompt_estimate_tokens=_read_int(payload.get("system_prompt_estimate_tokens")),
        system_prompt_section_count=_read_int(payload.get("system_prompt_section_count")),
        system_prompt_sections=_read_context_sections(payload.get("system_prompt_sections")),
        messages_estimate_tokens=_read_int(payload.get("messages_estimate_tokens")),
        tools_estimate_tokens=_read_int(payload.get("tools_estimate_tokens")),
        message_user_estimate_tokens=_read_int(payload.get("message_user_estimate_tokens")),
        message_assistant_estimate_tokens=_read_int(payload.get("message_assistant_estimate_tokens")),
        message_tool_estimate_tokens=_read_int(payload.get("message_tool_estimate_tokens")),
        message_other_estimate_tokens=_read_int(payload.get("message_other_estimate_tokens")),
        returned_tool_call_count=_read_int(payload.get("returned_tool_call_count")),
        content_chars=_read_int(payload.get("content_chars")),
        reasoning_chars=_read_int(payload.get("reasoning_chars")),
        tool_context_window_mode=_read_str(payload.get("tool_context_window_mode"), default="off"),
        pending_tool_exchange_count=_read_int(payload.get("pending_tool_exchange_count")),
        pending_tool_message_count=_read_int(payload.get("pending_tool_message_count")),
        compacted_tool_observation_count=_read_int(payload.get("compacted_tool_observation_count")),
        tool_state_message_estimate_tokens=_read_int(payload.get("tool_state_message_estimate_tokens")),
        tool_pending_message_estimate_tokens=_read_int(payload.get("tool_pending_message_estimate_tokens")),
        workflow_rule_selection_mode=_read_str(payload.get("workflow_rule_selection_mode"), default="none"),
        workflow_rule_pack_names=_read_string_list(payload.get("workflow_rule_pack_names")),
        workflow_rules_estimate_tokens=_read_int(payload.get("workflow_rules_estimate_tokens")),
        created_at=event.created_at,
    )


def _summarize_calls(calls: list[TokenUsageCall]) -> _Totals:
    totals = _Totals()
    for call in calls:
        totals.add(call)
    return totals


def _read_context_sections(value: object) -> list[TokenUsageContextSection]:
    if not isinstance(value, list):
        return []
    sections: list[TokenUsageContextSection] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _read_str(item.get("name"))
        if not name:
            continue
        sections.append(
            TokenUsageContextSection(
                name=name,
                tokens=_read_int(item.get("tokens")),
                chars=_read_int(item.get("chars")),
                item_count=_read_int(item.get("item_count")),
                pack_names=_read_string_list(item.get("pack_names")),
                selection_mode=_read_optional_str(item.get("selection_mode")),
            )
        )
    return sections


def _bucketize(
    calls: list[TokenUsageCall],
    *,
    key_getter: Callable[[TokenUsageCall], str],
    limit: int,
) -> list[TokenUsageBucket]:
    grouped: dict[str, _Totals] = {}
    for call in calls:
        raw_key = str(key_getter(call)).strip()
        key = raw_key or "unknown"
        grouped.setdefault(key, _Totals()).add(call)
    buckets = [
        TokenUsageBucket(
            key=key,
            call_count=totals.call_count,
            prompt_tokens=totals.prompt_tokens,
            completion_tokens=totals.completion_tokens,
            total_tokens=totals.total_tokens,
            estimated_count=totals.estimated_count,
            provider_count=totals.provider_count,
        )
        for key, totals in grouped.items()
    ]
    buckets.sort(key=lambda item: (item.total_tokens, item.call_count, item.key), reverse=True)
    return buckets[:limit]


def _validate_limit(name: str, value: int, *, maximum: int) -> int:
    if not isinstance(value, int):
        raise ValidationError(f"{name} must be int.")
    if value <= 0:
        raise ValidationError(f"{name} must be positive.")
    return min(value, maximum)


def _normalize_required(name: str, value: str) -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a non-empty string.")
    normalized = value.strip()
    if not normalized:
        raise ValidationError(f"{name} must be a non-empty string.")
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _read_str(value: object, *, default: str = "") -> str:
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or default
    if value is None:
        return default
    return str(value).strip() or default


def _read_optional_str(value: object) -> str | None:
    normalized = _read_str(value)
    return normalized or None


def _read_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        normalized = _read_str(item)
        if normalized:
            output.append(normalized)
    return output


def _read_int(value: object) -> int:
    parsed = _read_optional_int(value)
    return parsed if parsed is not None else 0


def _read_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(value, 0)
    if isinstance(value, float):
        return max(int(value), 0)
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.isdigit():
            return max(int(normalized), 0)
    return None
