"""Cursor persistence for mid-term flushing."""

from __future__ import annotations

import json
from pathlib import Path

from app.runtime.mid_term.models import FlushCursor
from app.runtime.mid_term.shared import format_iso, parse_iso_datetime, read_json, write_json_atomic


class MidTermFlushCursorStore:
    """Persist last flushed event per session and agent."""

    def __init__(self, root_dir: Path) -> None:
        self._root_dir = root_dir

    def load_cursor(self, *, session_id: str, agent_id: str) -> FlushCursor:
        path = self._cursor_path(session_id=session_id, agent_id=agent_id)
        if not path.exists():
            return FlushCursor(last_event_id=None, last_flushed_at=None)
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            return FlushCursor(last_event_id=None, last_flushed_at=None)
        raw_event_id = payload.get("last_event_id")
        raw_flushed_at = payload.get("last_flushed_at")
        last_event_id = str(raw_event_id).strip() if isinstance(raw_event_id, str) and raw_event_id.strip() else None
        last_flushed_at = parse_iso_datetime(raw_flushed_at)
        return FlushCursor(last_event_id=last_event_id, last_flushed_at=last_flushed_at)

    def save_cursor(self, *, session_id: str, agent_id: str, cursor: FlushCursor) -> None:
        path = self._cursor_path(session_id=session_id, agent_id=agent_id)
        payload = {
            "last_event_id": cursor.last_event_id,
            "last_flushed_at": format_iso(cursor.last_flushed_at) if cursor.last_flushed_at is not None else None,
        }
        write_json_atomic(path, payload)

    def _cursor_path(self, *, session_id: str, agent_id: str) -> Path:
        base = self._root_dir / "agents" / agent_id / "mid_term" / "flush_cursors"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{session_id}.json"
