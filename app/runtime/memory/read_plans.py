"""Read scope planning for runtime memory access."""

from __future__ import annotations

from app.memory.models import MemoryScope
from app.runtime.agent_capability import AgentCapability
from app.runtime.memory.models import ReadPlan


def build_context_read_plan(
    capability: AgentCapability,
    session_id: str,
    *,
    include_short: bool = True,
) -> ReadPlan:
    scopes = list(capability.memory_read_scopes)
    if not include_short:
        scopes = [scope for scope in scopes if scope != MemoryScope.AGENT_SHORT]
    short_session_id = None
    if MemoryScope.AGENT_SHORT in scopes and not capability.allow_cross_session_short_read:
        short_session_id = session_id
    return ReadPlan(include_scopes=scopes, short_session_id=short_session_id)


def build_agent_read_plan(capability: AgentCapability, session_id: str | None) -> ReadPlan:
    scopes = list(capability.memory_read_scopes)
    short_session_id = None
    if MemoryScope.AGENT_SHORT in scopes:
        if capability.allow_cross_session_short_read:
            short_session_id = None
        else:
            # 非会话上下文查询默认不扫描 short，防止在 API/管理接口跨会话泄露短期记忆。
            if session_id is None:
                scopes = [scope for scope in scopes if scope != MemoryScope.AGENT_SHORT]
            else:
                short_session_id = session_id
    return ReadPlan(include_scopes=scopes, short_session_id=short_session_id)
