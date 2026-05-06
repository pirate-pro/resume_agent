"""Tests for the multi-agent definition registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.errors import ValidationError
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability, AgentCapabilityRegistry, load_agent_capability_registry
from app.runtime.agent_registry import AgentRegistry, load_agent_registry

__all__ = []


def _write_docs(root: Path, agent_id: str, *, agent_text: str | None = None, soul_text: str | None = None) -> None:
    agent_dir = root / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "AGENT.md").write_text(agent_text or f"# {agent_id} agent", encoding="utf-8")
    (agent_dir / "SOUL.md").write_text(soul_text or f"# {agent_id} soul", encoding="utf-8")


def _capability_registry() -> AgentCapabilityRegistry:
    return AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["*"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
            ),
            "resume_agent": AgentCapability(
                agent_id="resume_agent",
                allowed_tools=["session_read_file", "memory_search"],
                memory_read_scopes=[MemoryScope.AGENT_LONG, MemoryScope.SHARED_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
                allow_cross_session_short_read=False,
            ),
        }
    )


def _registry_payload() -> dict[str, object]:
    return {
        "schema": "agents",
        "agents": [
            {
                "agent_id": "agent_main",
                "display_name": "MainCareerAgent",
                "description": "主 agent",
                "role": "main_orchestrator",
                "enabled": True,
                "is_main_agent": True,
                "document_agent_id": "default",
                "can_invoke_agents": True,
                "invokable_agent_ids": ["resume_agent"],
            },
            {
                "agent_id": "resume_agent",
                "display_name": "ResumeAgent",
                "description": "简历 agent",
                "role": "resume_parser",
                "enabled": True,
                "is_main_agent": False,
                "document_agent_id": "resume_agent",
                "can_invoke_agents": False,
                "invokable_agent_ids": [],
            },
        ],
    }


def _registry(tmp_path: Path) -> AgentRegistry:
    agents_dir = tmp_path / "agents"
    _write_docs(agents_dir, "default", agent_text="# Main Rules", soul_text="# Main Soul")
    _write_docs(agents_dir, "resume_agent", agent_text="# Resume Rules", soul_text="# Resume Soul")
    return AgentRegistry.from_payload(
        _registry_payload(),
        capability_registry=_capability_registry(),
        document_repository=MarkdownAgentDocumentRepository(agents_dir=agents_dir),
    )


def test_agent_registry_loads_definitions_documents_and_capabilities(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    assert [agent.agent_id for agent in registry.list_agents()] == ["agent_main", "resume_agent"]
    assert registry.get_main_agent().agent_id == "agent_main"
    assert registry.documents_for("agent_main").agent_markdown == "# Main Rules"
    assert registry.documents_for("resume_agent").agent_markdown == "# Resume Rules"
    assert registry.can_use_tool("resume_agent", "session_read_file") is True
    assert registry.can_use_tool("resume_agent", "memory_write") is False
    assert registry.can_read_memory("resume_agent", MemoryScope.SHARED_LONG) is True
    assert registry.can_write_memory("resume_agent", MemoryScope.SHARED_LONG) is False


def test_agent_registry_checks_invocation_direction(tmp_path: Path) -> None:
    registry = _registry(tmp_path)

    assert registry.can_invoke("agent_main", "resume_agent") is True
    assert registry.can_invoke("resume_agent", "agent_main") is False


def test_agent_registry_requires_single_enabled_main_agent(tmp_path: Path) -> None:
    payload = _registry_payload()
    agents = payload["agents"]
    assert isinstance(agents, list)
    agents[1]["is_main_agent"] = True
    agents[1]["can_invoke_agents"] = True
    agents[1]["invokable_agent_ids"] = ["agent_main"]

    with pytest.raises(ValidationError, match="exactly one enabled main agent"):
        AgentRegistry.from_payload(
            payload,
            capability_registry=_capability_registry(),
            document_repository=MarkdownAgentDocumentRepository(agents_dir=tmp_path / "agents"),
        )


def test_agent_registry_validates_invokable_targets(tmp_path: Path) -> None:
    payload = _registry_payload()
    agents = payload["agents"]
    assert isinstance(agents, list)
    agents[0]["invokable_agent_ids"] = ["missing_agent"]

    with pytest.raises(ValidationError, match="unknown invokable agent"):
        AgentRegistry.from_payload(
            payload,
            capability_registry=_capability_registry(),
            document_repository=MarkdownAgentDocumentRepository(agents_dir=tmp_path / "agents"),
        )


def test_agent_registry_validates_capability_for_each_agent(tmp_path: Path) -> None:
    payload = _registry_payload()
    capability_registry = AgentCapabilityRegistry(
        {
            "agent_main": AgentCapability(
                agent_id="agent_main",
                allowed_tools=["*"],
                memory_read_scopes=[MemoryScope.AGENT_LONG],
                memory_write_scopes=[MemoryScope.AGENT_LONG],
            )
        }
    )

    with pytest.raises(ValidationError, match="Unknown agent_id in capability registry: resume_agent"):
        AgentRegistry.from_payload(
            payload,
            capability_registry=capability_registry,
            document_repository=MarkdownAgentDocumentRepository(agents_dir=tmp_path / "agents"),
        )


def test_load_agent_registry_from_file(tmp_path: Path) -> None:
    agents_dir = tmp_path / "agents"
    _write_docs(agents_dir, "default", agent_text="# Main", soul_text="# Main Soul")
    _write_docs(agents_dir, "resume_agent", agent_text="# Resume", soul_text="# Resume Soul")
    config_path = tmp_path / "agents.json"
    config_path.write_text(json.dumps(_registry_payload(), ensure_ascii=False), encoding="utf-8")

    registry = load_agent_registry(
        config_path,
        capability_registry=_capability_registry(),
        document_repository=MarkdownAgentDocumentRepository(agents_dir=agents_dir),
    )

    assert registry.get_main_agent().agent_id == "agent_main"
    assert registry.can_invoke("agent_main", "resume_agent") is True


def test_production_agent_registry_config_is_loadable() -> None:
    capability_registry = load_agent_capability_registry(Path("app/config/agent_capabilities.json"))
    registry = load_agent_registry(
        Path("app/config/agents.json"),
        capability_registry=capability_registry,
        document_repository=MarkdownAgentDocumentRepository(agents_dir=Path("app/agents")),
    )

    assert registry.get_main_agent().agent_id == "agent_main"
    assert registry.can_invoke("agent_main", "resume_agent") is True
    assert registry.can_invoke("resume_agent", "agent_main") is False
    assert registry.documents_for("resume_agent").agent_markdown is not None
