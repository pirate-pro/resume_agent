"""Agent 能力矩阵与配置加载。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.errors import StorageError, ValidationError
from app.memory.models import MemoryScope

__all__ = [
    "AgentCapability",
    "AgentCapabilityRegistry",
    "load_agent_capability_registry",
]


@dataclass(slots=True)
class AgentCapability:
    """单个 agent 的权限配置。"""

    agent_id: str
    allowed_tools: list[str]
    allowed_skills: list[str]
    default_skills: list[str]
    memory_read_scopes: list[MemoryScope]
    memory_write_scopes: list[MemoryScope]
    allow_cross_session_short_read: bool = True
    allow_cross_agent_memory_read: bool = False
    allow_cross_agent_memory_write: bool = False

    def __post_init__(self) -> None:
        self.agent_id = _normalize_non_empty("agent_id", self.agent_id)
        self.allowed_tools = _normalize_tool_list(self.allowed_tools)
        self.allowed_skills = _normalize_skill_list(self.allowed_skills, field_name="allowed_skills")
        self.default_skills = _normalize_skill_list(self.default_skills, field_name="default_skills")
        self.memory_read_scopes = _normalize_scope_list(self.memory_read_scopes, field_name="memory_read_scopes")
        self.memory_write_scopes = _normalize_scope_list(self.memory_write_scopes, field_name="memory_write_scopes")
        for skill_name in self.default_skills:
            if not self.allows_skill(skill_name):
                raise ValidationError("default_skills must be a subset of allowed_skills.")

    def allows_tool(self, tool_name: str) -> bool:
        normalized = _normalize_non_empty("tool_name", tool_name)
        return "*" in self.allowed_tools or normalized in self.allowed_tools

    def allows_skill(self, skill_name: str) -> bool:
        normalized = _normalize_non_empty("skill_name", skill_name)
        return "*" in self.allowed_skills or normalized in self.allowed_skills

    def resolve_skill_names(self, requested_skill_names: list[str] | None = None) -> list[str]:
        requested = self.default_skills if not requested_skill_names else _normalize_skill_list(
            requested_skill_names,
            field_name="requested_skill_names",
        )
        output: list[str] = []
        seen: set[str] = set()
        for skill_name in requested:
            if not self.allows_skill(skill_name):
                raise ValidationError(f"Skill not allowed for agent '{self.agent_id}': {skill_name}")
            if skill_name in seen:
                continue
            output.append(skill_name)
            seen.add(skill_name)
        if not output:
            raise ValidationError("resolved skill_names cannot be empty.")
        return output

    def can_read_scope(self, scope: MemoryScope) -> bool:
        return scope in self.memory_read_scopes

    def can_write_scope(self, scope: MemoryScope) -> bool:
        return scope in self.memory_write_scopes


class AgentCapabilityRegistry:
    """按 agent_id 查询权限矩阵。"""

    def __init__(self, capabilities: dict[str, AgentCapability]) -> None:
        if not isinstance(capabilities, dict) or not capabilities:
            raise ValidationError("capabilities must be a non-empty dictionary.")
        self._capabilities = dict(capabilities)

    def require(self, agent_id: str) -> AgentCapability:
        normalized = _normalize_non_empty("agent_id", agent_id)
        capability = self._capabilities.get(normalized)
        if capability is None:
            raise ValidationError(f"Unknown agent_id in capability registry: {normalized}")
        return capability

    def get(self, agent_id: str) -> AgentCapability | None:
        normalized = _normalize_non_empty("agent_id", agent_id)
        return self._capabilities.get(normalized)

    def all_agent_ids(self) -> list[str]:
        return sorted(self._capabilities.keys())

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "AgentCapabilityRegistry":
        if not isinstance(payload, dict):
            raise ValidationError("capability payload must be object.")
        raw_agents = payload.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            raise ValidationError("capability payload must include non-empty agents list.")
        output: dict[str, AgentCapability] = {}
        for raw in raw_agents:
            capability = _parse_capability_item(raw)
            if capability.agent_id in output:
                raise ValidationError(f"Duplicate agent capability config: {capability.agent_id}")
            output[capability.agent_id] = capability
        return cls(output)

    @classmethod
    def for_tests(cls) -> "AgentCapabilityRegistry":
        # 测试默认覆盖常见 agent，避免每个测试重复拼装矩阵。
        payload = {
            "schema": "agent_capabilities_v1",
            "agents": [
                _default_agent_payload("agent_main"),
                _default_agent_payload("agent_alpha"),
                _default_agent_payload("agent_beta"),
                _default_agent_payload("agent_other"),
                _file_reader_child_agent_payload("resume_agent"),
                _file_reader_child_agent_payload("job_agent"),
            ],
        }
        return cls.from_payload(payload)


def load_agent_capability_registry(path: Path) -> AgentCapabilityRegistry:
    if not isinstance(path, Path):
        raise ValidationError("capability path must be pathlib.Path.")
    if not path.exists():
        raise StorageError(f"Agent capability file does not exist: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageError(f"Failed to read agent capability file '{path}': {exc}") from exc
    return AgentCapabilityRegistry.from_payload(payload)


def _parse_capability_item(raw: Any) -> AgentCapability:
    if not isinstance(raw, dict):
        raise ValidationError("agent capability item must be object.")
    raw_read_scopes = raw.get("memory_read_scopes")
    raw_write_scopes = raw.get("memory_write_scopes")
    if not isinstance(raw_read_scopes, list) or not raw_read_scopes:
        raise ValidationError("memory_read_scopes must be a non-empty list.")
    if not isinstance(raw_write_scopes, list) or not raw_write_scopes:
        raise ValidationError("memory_write_scopes must be a non-empty list.")
    return AgentCapability(
        agent_id=str(raw.get("agent_id", "")),
        allowed_tools=_normalize_tool_items(raw.get("allowed_tools")),
        allowed_skills=_normalize_skill_items(raw.get("allowed_skills")),
        default_skills=_normalize_skill_items(raw.get("default_skills")),
        memory_read_scopes=[_parse_scope(item, field_name="memory_read_scopes") for item in raw_read_scopes],
        memory_write_scopes=[_parse_scope(item, field_name="memory_write_scopes") for item in raw_write_scopes],
        allow_cross_session_short_read=bool(raw.get("allow_cross_session_short_read", True)),
        allow_cross_agent_memory_read=bool(raw.get("allow_cross_agent_memory_read", False)),
        allow_cross_agent_memory_write=bool(raw.get("allow_cross_agent_memory_write", False)),
    )


def _normalize_non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string.")
    return value.strip()


def _normalize_tool_items(raw: Any) -> list[str]:
    if raw is None:
        return ["*"]
    if not isinstance(raw, list) or not raw:
        raise ValidationError("allowed_tools must be a non-empty list.")
    return _normalize_tool_list([str(item) for item in raw])


def _normalize_skill_items(raw: Any) -> list[str]:
    if raw is None:
        return ["base"]
    if not isinstance(raw, list) or not raw:
        raise ValidationError("skill list must be a non-empty list.")
    return _normalize_skill_list([str(item) for item in raw], field_name="skill")


def _normalize_tool_list(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in items:
        tool = _normalize_non_empty("allowed_tool", raw)
        if tool in seen:
            continue
        output.append(tool)
        seen.add(tool)
    if not output:
        raise ValidationError("allowed_tools cannot be empty after normalization.")
    return output


def _normalize_skill_list(items: list[str], *, field_name: str) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in items:
        skill = _normalize_non_empty(field_name, raw)
        if skill in seen:
            continue
        output.append(skill)
        seen.add(skill)
    if not output:
        raise ValidationError(f"{field_name} cannot be empty after normalization.")
    return output


def _normalize_scope_list(items: list[MemoryScope], field_name: str) -> list[MemoryScope]:
    output: list[MemoryScope] = []
    seen: set[MemoryScope] = set()
    for item in items:
        if not isinstance(item, MemoryScope):
            raise ValidationError(f"{field_name} must contain MemoryScope items.")
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    if not output:
        raise ValidationError(f"{field_name} cannot be empty.")
    return output


def _parse_scope(value: Any, field_name: str) -> MemoryScope:
    if isinstance(value, MemoryScope):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} item must be non-empty string.")
    normalized = value.strip()
    try:
        return MemoryScope(normalized)
    except ValueError as exc:
        raise ValidationError(f"Unsupported memory scope '{normalized}' in {field_name}.") from exc


def _default_agent_payload(agent_id: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "allowed_tools": ["*"],
        "allowed_skills": ["*"],
        "default_skills": ["base", "memory", "memory-editor", "tools", "file-reader"],
        "memory_read_scopes": ["agent_short", "agent_long", "shared_long"],
        "memory_write_scopes": ["agent_short", "agent_long", "shared_long"],
        "allow_cross_session_short_read": True,
        "allow_cross_agent_memory_read": False,
        "allow_cross_agent_memory_write": False,
    }


def _file_reader_child_agent_payload(agent_id: str) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "allowed_tools": [
            "session_list_artifacts",
            "session_plan_artifact_access",
            "session_read_artifact",
            "session_search_artifact",
            "memory_search",
        ],
        "allowed_skills": ["base", "tools", "file-reader"],
        "default_skills": ["base", "tools", "file-reader"],
        "memory_read_scopes": ["agent_long", "shared_long"],
        "memory_write_scopes": ["agent_long"],
        "allow_cross_session_short_read": False,
        "allow_cross_agent_memory_read": False,
        "allow_cross_agent_memory_write": False,
    }
