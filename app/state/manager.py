"""High-level orchestration for state records."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from app.core.errors import ValidationError
from app.state.contracts import StateStore
from app.state.models import StateRecord, StateScope, StateStatus

__all__ = ["StateManager"]


class StateManager:
    """Manage per-agent and shared session state."""

    def __init__(self, store: StateStore) -> None:
        self._store = store

    def set_agent_state(
        self,
        *,
        session_id: str,
        agent_id: str,
        key: str,
        value: str,
        source_run_id: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> StateRecord:
        normalized_session_id = _require_non_empty("session_id", session_id)
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        normalized_key = _require_non_empty("key", key)
        normalized_value = _require_non_empty("value", value)
        normalized_metadata = _normalize_metadata(metadata)
        normalized_source_run_id = _normalize_optional("source_run_id", source_run_id)
        now = datetime.now(UTC)
        existing = self._store.get_record(
            scope=StateScope.AGENT_SESSION,
            session_id=normalized_session_id,
            key=normalized_key,
            agent_id=normalized_agent_id,
            include_archived=False,
        )
        record = StateRecord(
            state_id=existing.state_id if existing is not None else f"state_{uuid4().hex[:12]}",
            scope=StateScope.AGENT_SESSION,
            owner_agent_id=normalized_agent_id,
            session_id=normalized_session_id,
            key=normalized_key,
            value=normalized_value,
            status=StateStatus.ACTIVE,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            version=existing.version + 1 if existing is not None else 1,
            source_run_id=normalized_source_run_id,
            metadata=normalized_metadata,
        )
        self._store.upsert_record(record)
        return record

    def list_agent_state(self, *, session_id: str, agent_id: str) -> list[StateRecord]:
        normalized_session_id = _require_non_empty("session_id", session_id)
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        return self._store.list_records(
            scope=StateScope.AGENT_SESSION,
            session_id=normalized_session_id,
            agent_id=normalized_agent_id,
            include_archived=False,
        )

    def clear_agent_state(
        self,
        *,
        session_id: str,
        agent_id: str,
        keys: list[str] | None = None,
    ) -> int:
        normalized_session_id = _require_non_empty("session_id", session_id)
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        normalized_keys = _normalize_keys(keys)
        return self._store.archive_records(
            scope=StateScope.AGENT_SESSION,
            session_id=normalized_session_id,
            keys=normalized_keys,
            now=datetime.now(UTC),
            agent_id=normalized_agent_id,
        )

    def publish_agent_state(
        self,
        *,
        session_id: str,
        agent_id: str,
        keys: list[str],
    ) -> list[StateRecord]:
        normalized_session_id = _require_non_empty("session_id", session_id)
        normalized_agent_id = _require_non_empty("agent_id", agent_id)
        normalized_keys = _normalize_required_keys(keys)
        now = datetime.now(UTC)
        published: list[StateRecord] = []

        for key in normalized_keys:
            source = self._store.get_record(
                scope=StateScope.AGENT_SESSION,
                session_id=normalized_session_id,
                key=key,
                agent_id=normalized_agent_id,
                include_archived=False,
            )
            if source is None:
                raise ValidationError(
                    f"Cannot publish missing agent state: session_id={normalized_session_id} "
                    f"agent_id={normalized_agent_id} key={key}"
                )
            existing_shared = self._store.get_record(
                scope=StateScope.SHARED_SESSION,
                session_id=normalized_session_id,
                key=key,
                include_archived=False,
            )
            metadata = dict(source.metadata)
            metadata["published_from_scope"] = StateScope.AGENT_SESSION.value
            metadata["published_from_agent_id"] = normalized_agent_id
            metadata["published_from_state_id"] = source.state_id
            record = StateRecord(
                state_id=existing_shared.state_id if existing_shared is not None else f"state_{uuid4().hex[:12]}",
                scope=StateScope.SHARED_SESSION,
                owner_agent_id=normalized_agent_id,
                session_id=normalized_session_id,
                key=key,
                value=source.value,
                status=StateStatus.ACTIVE,
                created_at=existing_shared.created_at if existing_shared is not None else now,
                updated_at=now,
                version=existing_shared.version + 1 if existing_shared is not None else 1,
                source_run_id=source.source_run_id,
                metadata=metadata,
            )
            self._store.upsert_record(record)
            published.append(record)
        return published

    def list_shared_state(self, *, session_id: str) -> list[StateRecord]:
        normalized_session_id = _require_non_empty("session_id", session_id)
        return self._store.list_records(
            scope=StateScope.SHARED_SESSION,
            session_id=normalized_session_id,
            include_archived=False,
        )

    def revoke_shared_state(self, *, session_id: str, keys: list[str] | None = None) -> int:
        normalized_session_id = _require_non_empty("session_id", session_id)
        normalized_keys = _normalize_keys(keys)
        return self._store.archive_records(
            scope=StateScope.SHARED_SESSION,
            session_id=normalized_session_id,
            keys=normalized_keys,
            now=datetime.now(UTC),
            agent_id=None,
        )


def _require_non_empty(field_name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string.")
    return value.strip()


def _normalize_optional(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_non_empty(field_name, value)


def _normalize_metadata(metadata: dict[str, str] | None) -> dict[str, str]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValidationError("metadata must be a dictionary.")
    normalized: dict[str, str] = {}
    for raw_key, raw_value in metadata.items():
        key = _require_non_empty("metadata key", str(raw_key))
        value = _require_non_empty("metadata value", str(raw_value))
        normalized[key] = value
    return normalized


def _normalize_keys(keys: list[str] | None) -> list[str] | None:
    if keys is None:
        return None
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in keys:
        key = _require_non_empty("key", raw)
        if key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def _normalize_required_keys(keys: list[str]) -> list[str]:
    normalized = _normalize_keys(keys)
    if not normalized:
        raise ValidationError("keys must contain at least one non-empty string.")
    return normalized
