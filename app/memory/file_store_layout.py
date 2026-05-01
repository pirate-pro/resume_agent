"""Filesystem layout helpers for file-backed memory storage."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from app.core.errors import ValidationError
from app.memory.file_models import format_memory_time
from app.memory.file_store_common import empty_long_term_payload, require_non_empty
from app.memory.file_store_io import ensure_file, write_json_payload

__all__ = ["MemoryFileLayout"]


class MemoryFileLayout:
    """Resolve and initialize memory storage paths."""

    def __init__(self, root_dir: Path) -> None:
        if not isinstance(root_dir, Path):
            raise ValidationError("root_dir must be pathlib.Path.")
        self._root_dir = root_dir

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def ensure_shared_layout(self) -> None:
        (self._root_dir / "shared" / "mid_term" / "daily").mkdir(parents=True, exist_ok=True)
        ensure_file(self._root_dir / "shared" / "facts.jsonl")
        ensure_file(self._root_dir / "shared" / "pending_promotions.jsonl")
        ensure_file(self._root_dir / "shared" / "mid_term" / "rolling.md", "# Rolling Context\n")
        self._ensure_long_term_file(self._root_dir / "shared" / "long_term.json", scope="shared", agent_id=None)

    def ensure_agent_layout(self, agent_id: str) -> None:
        normalized = require_non_empty("agent_id", agent_id)
        agent_dir = self._root_dir / "agents" / normalized
        (agent_dir / "mid_term" / "daily").mkdir(parents=True, exist_ok=True)
        ensure_file(agent_dir / "facts.jsonl")
        ensure_file(agent_dir / "mid_term" / "rolling.md", "# Rolling Context\n")
        self._ensure_long_term_file(agent_dir / "long_term_overlay.json", scope="agent", agent_id=normalized)

    def long_term_path(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self.ensure_shared_layout()
            return self._root_dir / "shared" / "long_term.json"
        if scope == "agent" and agent_id:
            self.ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "long_term_overlay.json"
        raise ValidationError("invalid long_term path scope.")

    def facts_path(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self.ensure_shared_layout()
            return self._root_dir / "shared" / "facts.jsonl"
        if scope == "agent" and agent_id:
            self.ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "facts.jsonl"
        raise ValidationError("invalid facts path scope.")

    def mid_term_dir(self, *, scope: str, agent_id: str | None) -> Path:
        if scope == "shared":
            self.ensure_shared_layout()
            return self._root_dir / "shared" / "mid_term"
        if scope == "agent" and agent_id:
            self.ensure_agent_layout(agent_id)
            return self._root_dir / "agents" / agent_id / "mid_term"
        raise ValidationError("invalid mid_term path scope.")

    def _ensure_long_term_file(self, path: Path, *, scope: str, agent_id: str | None) -> None:
        if path.exists():
            return
        now = format_memory_time(datetime.now(UTC))
        payload = empty_long_term_payload(scope=scope, agent_id=agent_id, now=now)
        write_json_payload(path, payload)
