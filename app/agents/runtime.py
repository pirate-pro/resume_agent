from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def serialize_payload(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, (str, int, float, bool)):
        return payload
    if isinstance(payload, list):
        return [serialize_payload(item) for item in payload]
    if isinstance(payload, dict):
        return {str(key): serialize_payload(value) for key, value in payload.items()}
    if hasattr(payload, "to_dict"):
        return payload.to_dict()
    if is_dataclass(payload):
        return asdict(payload)
    return payload


@dataclass(slots=True)
class AgentToolTrace:
    tool_name: str
    status: str
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class AgentResult:
    status: str
    output: Any = None
    observations: list[str] = field(default_factory=list)
    tool_traces: list[AgentToolTrace] = field(default_factory=list)
    confidence: float | None = None
    next_stage_hint: str | None = None
    failure_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "output": serialize_payload(self.output),
            "observations": self.observations,
            "tool_traces": [trace.to_dict() for trace in self.tool_traces],
            "confidence": self.confidence,
            "next_stage_hint": self.next_stage_hint,
            "failure_reason": self.failure_reason,
            "metadata": serialize_payload(self.metadata),
        }
