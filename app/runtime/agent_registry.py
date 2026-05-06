"""Agent definition registry for multi-agent scaffolding."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.domain.models import AgentIdentityDocuments
from app.domain.protocols import AgentDocumentRepository
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry

__all__ = [
    "AgentDefinition",
    "AgentRegistry",
    "load_agent_registry",
]

_AGENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


@dataclass(slots=True)
class AgentDefinition:
    """Static metadata for one agent."""

    agent_id: str
    display_name: str
    description: str
    role: str
    enabled: bool
    is_main_agent: bool
    document_agent_id: str
    can_invoke_agents: bool
    invokable_agent_ids: list[str]

    def __post_init__(self) -> None:
        self.agent_id = _normalize_agent_id(self.agent_id)
        self.display_name = _normalize_non_empty("display_name", self.display_name)
        self.description = _normalize_non_empty("description", self.description)
        self.role = _normalize_non_empty("role", self.role)
        self.document_agent_id = _normalize_agent_id(self.document_agent_id)
        if not isinstance(self.enabled, bool):
            raise ValidationError("agent enabled must be bool.")
        if not isinstance(self.is_main_agent, bool):
            raise ValidationError("agent is_main_agent must be bool.")
        if not isinstance(self.can_invoke_agents, bool):
            raise ValidationError("agent can_invoke_agents must be bool.")
        self.invokable_agent_ids = _normalize_invokable_agent_ids(self.invokable_agent_ids)
        if not self.can_invoke_agents and self.invokable_agent_ids:
            raise ValidationError("invokable_agent_ids must be empty when can_invoke_agents is false.")

    def allows_invocation(self, target_agent_id: str) -> bool:
        normalized_target = _normalize_agent_id(target_agent_id)
        if not self.enabled or not self.can_invoke_agents:
            return False
        return "*" in self.invokable_agent_ids or normalized_target in self.invokable_agent_ids


class AgentRegistry:
    """Read-only registry for agent metadata, documents, and capability checks."""

    def __init__(
        self,
        definitions: dict[str, AgentDefinition],
        *,
        capability_registry: AgentCapabilityRegistry,
        document_repository: AgentDocumentRepository,
    ) -> None:
        if not isinstance(definitions, dict) or not definitions:
            raise ValidationError("agent definitions must be a non-empty dictionary.")
        self._definitions = dict(definitions)
        self._capability_registry = capability_registry
        self._document_repository = document_repository
        self._validate()

    def list_agents(self, *, enabled_only: bool = False) -> list[AgentDefinition]:
        agents = list(self._definitions.values())
        if enabled_only:
            agents = [agent for agent in agents if agent.enabled]
        return agents

    def require(self, agent_id: str) -> AgentDefinition:
        normalized = _normalize_agent_id(agent_id)
        definition = self._definitions.get(normalized)
        if definition is None:
            raise ValidationError(f"Unknown agent_id in agent registry: {normalized}")
        return definition

    def get_main_agent(self) -> AgentDefinition:
        for definition in self._definitions.values():
            if definition.enabled and definition.is_main_agent:
                return definition
        raise ValidationError("agent registry has no enabled main agent.")

    def can_invoke(self, source_agent_id: str, target_agent_id: str) -> bool:
        source = self.require(source_agent_id)
        target = self.require(target_agent_id)
        if not target.enabled:
            return False
        return source.allows_invocation(target.agent_id)

    def capability_for(self, agent_id: str) -> AgentCapability:
        definition = self.require(agent_id)
        return self._capability_registry.require(definition.agent_id)

    def documents_for(self, agent_id: str) -> AgentIdentityDocuments:
        definition = self.require(agent_id)
        return self._document_repository.load_documents(definition.document_agent_id)

    def can_use_tool(self, agent_id: str, tool_name: str) -> bool:
        return self.capability_for(agent_id).allows_tool(tool_name)

    def can_read_memory(self, agent_id: str, scope: MemoryScope) -> bool:
        return self.capability_for(agent_id).can_read_scope(scope)

    def can_write_memory(self, agent_id: str, scope: MemoryScope) -> bool:
        return self.capability_for(agent_id).can_write_scope(scope)

    @classmethod
    def from_payload(
        cls,
        payload: dict[str, Any],
        *,
        capability_registry: AgentCapabilityRegistry,
        document_repository: AgentDocumentRepository,
    ) -> "AgentRegistry":
        if not isinstance(payload, dict):
            raise ValidationError("agent registry payload must be object.")
        raw_agents = payload.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            raise ValidationError("agent registry payload must include non-empty agents list.")
        definitions: dict[str, AgentDefinition] = {}
        for raw in raw_agents:
            definition = _parse_agent_definition(raw)
            if definition.agent_id in definitions:
                raise ValidationError(f"Duplicate agent definition: {definition.agent_id}")
            definitions[definition.agent_id] = definition
        return cls(
            definitions,
            capability_registry=capability_registry,
            document_repository=document_repository,
        )

    def _validate(self) -> None:
        main_agents = [agent.agent_id for agent in self._definitions.values() if agent.enabled and agent.is_main_agent]
        if len(main_agents) != 1:
            raise ValidationError("agent registry must contain exactly one enabled main agent.")
        for definition in self._definitions.values():
            self._capability_registry.require(definition.agent_id)
            for target_agent_id in definition.invokable_agent_ids:
                if target_agent_id == "*":
                    continue
                target = self._definitions.get(target_agent_id)
                if target is None:
                    raise ValidationError(
                        f"Agent '{definition.agent_id}' references unknown invokable agent: {target_agent_id}"
                    )
                if not target.enabled:
                    raise ValidationError(
                        f"Agent '{definition.agent_id}' references disabled invokable agent: {target_agent_id}"
                    )


def load_agent_registry(
    path: Path,
    *,
    capability_registry: AgentCapabilityRegistry,
    document_repository: AgentDocumentRepository,
) -> AgentRegistry:
    if not isinstance(path, Path):
        raise ValidationError("agent registry path must be pathlib.Path.")
    if not path.exists():
        raise StorageError(f"Agent registry file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Failed to read agent registry file '{path}': {exc}") from exc
    return AgentRegistry.from_payload(
        payload,
        capability_registry=capability_registry,
        document_repository=document_repository,
    )


def _parse_agent_definition(raw: Any) -> AgentDefinition:
    if not isinstance(raw, dict):
        raise ValidationError("agent definition item must be object.")
    return AgentDefinition(
        agent_id=str(raw.get("agent_id", "")),
        display_name=str(raw.get("display_name", "")),
        description=str(raw.get("description", "")),
        role=str(raw.get("role", "")),
        enabled=_parse_bool(raw.get("enabled", True), field_name="enabled"),
        is_main_agent=_parse_bool(raw.get("is_main_agent", False), field_name="is_main_agent"),
        document_agent_id=str(raw.get("document_agent_id") or raw.get("agent_id", "")),
        can_invoke_agents=_parse_bool(raw.get("can_invoke_agents", False), field_name="can_invoke_agents"),
        invokable_agent_ids=_raw_string_list(raw.get("invokable_agent_ids")),
    )


def _normalize_agent_id(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("agent_id must be a non-empty string.")
    normalized = value.strip()
    if not _AGENT_ID_PATTERN.fullmatch(normalized):
        raise ValidationError("agent_id contains invalid characters.")
    return normalized


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _raw_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValidationError("invokable_agent_ids must be list.")
    return [str(item) for item in raw]


def _parse_bool(raw: Any, *, field_name: str) -> bool:
    if not isinstance(raw, bool):
        raise ValidationError(f"{field_name} must be bool.")
    return raw


def _normalize_invokable_agent_ids(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = "*" if item == "*" else _normalize_agent_id(item)
        if normalized in seen:
            continue
        output.append(normalized)
        seen.add(normalized)
    return output
