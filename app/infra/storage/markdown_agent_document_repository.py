"""Markdown-backed AGENT.md and SOUL.md repository."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.errors import StorageError, ValidationError
from app.domain.models import AgentIdentityDocuments

__all__ = ["MarkdownAgentDocumentRepository"]
_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class MarkdownAgentDocumentRepository:
    """Load static AGENT.md and SOUL.md documents for one agent."""

    def __init__(self, agents_dir: Path) -> None:
        if not isinstance(agents_dir, Path):
            raise ValidationError("agents_dir must be a pathlib.Path.")
        self._agents_dir = agents_dir

    def load_documents(self, agent_id: str) -> AgentIdentityDocuments:
        normalized_agent_id = _normalize_agent_id(agent_id)
        self._validate_agents_dir()
        agent_markdown = self._read_document(agent_id=normalized_agent_id, filename="AGENT.md")
        soul_markdown = self._read_document(agent_id=normalized_agent_id, filename="SOUL.md")
        return AgentIdentityDocuments(
            agent_markdown=agent_markdown,
            soul_markdown=soul_markdown,
        )

    def _validate_agents_dir(self) -> None:
        if not self._agents_dir.exists():
            raise StorageError(f"agents_dir not found: {self._agents_dir}")
        if not self._agents_dir.is_dir():
            raise StorageError(f"agents_dir must be directory: {self._agents_dir}")

    def _read_document(self, agent_id: str, filename: str) -> str | None:
        path = self._resolve_document_path(agent_id=agent_id, filename=filename)
        if path is None:
            return None
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise StorageError(f"Failed to read document '{path}': {exc}") from exc
        if not content:
            raise StorageError(f"Agent document is empty: {path}")
        return content

    def _resolve_document_path(self, agent_id: str, filename: str) -> Path | None:
        candidates = [self._agents_dir / agent_id / filename]
        if agent_id != "default":
            candidates.append(self._agents_dir / "default" / filename)
        for candidate in candidates:
            if not candidate.exists():
                continue
            if not candidate.is_file():
                raise StorageError(f"Agent document must be a file: {candidate}")
            return candidate
        return None


def _normalize_agent_id(agent_id: str) -> str:
    if not isinstance(agent_id, str) or not agent_id.strip():
        raise ValidationError("agent_id must be a non-empty string.")
    normalized = agent_id.strip()
    if not _AGENT_ID_PATTERN.fullmatch(normalized):
        raise ValidationError("agent_id contains invalid characters.")
    return normalized
