from __future__ import annotations

from dataclasses import asdict, dataclass, field
from uuid import uuid4


@dataclass(slots=True)
class AgentContextFrame:
    context_id: str
    agent_name: str
    mode: str
    task_id: str
    parent_context_id: str | None = None
    local_memory: dict = field(default_factory=dict)
    shared_refs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class AgentContextStore:
    def __init__(self) -> None:
        self._frames: dict[str, AgentContextFrame] = {}

    def new_context(
        self,
        *,
        agent_name: str,
        mode: str,
        task_id: str,
        parent_context_id: str | None = None,
        shared_refs: dict | None = None,
    ) -> AgentContextFrame:
        context = AgentContextFrame(
            context_id=str(uuid4()),
            agent_name=agent_name,
            mode=mode,
            task_id=task_id,
            parent_context_id=parent_context_id,
            shared_refs=shared_refs or {},
        )
        self._frames[context.context_id] = context
        return context

    def to_dict(self) -> dict:
        return {context_id: frame.to_dict() for context_id, frame in self._frames.items()}
