"""Small fact packet for final-answer recovery.

The tool loop needs repair-oriented context, including compact tool call
attempts. Final answers should instead use committed tool results and durable
refs. This module builds that narrower finalization view.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.runtime.agent.tool_context_window import sanitize_messages_for_final_answer
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object

__all__ = [
    "FinalAnswerRecoveryContext",
    "FinalizationPacket",
    "build_final_answer_recovery_context",
    "build_finalization_packet",
]

_FACT_KEYS = {
    "tool",
    "success",
    "record_type",
    "ids",
    "record_id",
    "status",
    "found",
    "title",
    "summary",
    "score",
    "recommendation",
    "artifact_refs",
    "evidence_refs",
    "source_refs",
    "link_refs",
    "record",
    "items_preview",
    "next_actions",
    "risks",
    "completion_hint",
    "source_alignment_repaired",
}
_OMITTED_FACT_KEYS = {
    "full_result_hint",
    "model_view",
    "source_alignment_guidance",
    "workflow_completion_guidance",
    "tool_search_guidance",
    "revealed_tool_names",
    "revealed_tool_groups",
    "older_observation_summary",
}
_ID_KEY_HINTS = (
    "_id",
    "_ids",
    "_ref",
    "_refs",
)
_INTERNAL_REF_KEYS = {
    "agent_id",
    "child_run_id",
    "ledger_record_id",
    "owner_agent_id",
    "parent_run_id",
    "run_id",
    "session_id",
    "source_session_id",
    "target_agent_id",
    "task_group_id",
    "task_id",
    "tool_call_id",
}
_INTERNAL_REF_PREFIXES = ("run_", "sess_", "task_", "task_group_", "call_", "tool_call_")
_INTERNAL_REF_VALUES = {"agent_main", "resume_agent", "job_agent"}
_MAX_FACTS = 12


@dataclass(slots=True)
class FinalizationPacket:
    """Grounded facts available to the final answer."""

    user_goal: str
    phase: str | None = None
    next_action: str | None = None
    final_answer_ready: bool = False
    required_outputs: list[str] = field(default_factory=list)
    missing_outputs: list[str] = field(default_factory=list)
    known_refs: dict[str, str] = field(default_factory=dict)
    completed_tools: list[str] = field(default_factory=list)
    product_refs: list[str] = field(default_factory=list)
    artifact_refs: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_grounding(self) -> bool:
        return bool(self.known_refs or self.completed_tools or self.product_refs or self.artifact_refs or self.facts)

    def to_payload(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "user_goal": self.user_goal,
                "phase": self.phase,
                "next_action": self.next_action,
                "final_answer_ready": self.final_answer_ready,
                "required_outputs": self.required_outputs,
                "missing_outputs": self.missing_outputs,
                "known_refs": self.known_refs,
                "completed_tools": self.completed_tools,
                "product_refs": self.product_refs,
                "artifact_refs": self.artifact_refs,
                "facts": self.facts,
                "warnings": self.warnings,
                "final_answer_rules": [
                    "Only summarize committed facts in this packet.",
                    "Do not mention attempted tool arguments, repaired inputs, hidden runtime state, or unsupported facts.",
                    "If an expected detail is missing from the packet, say it was not provided instead of inventing it.",
                ],
            }
        )

    def to_event_payload(self, *, used_for_recovery: bool) -> dict[str, Any]:
        payload = self.to_payload()
        return {
            "used_for_recovery": used_for_recovery,
            "phase": self.phase,
            "final_answer_ready": self.final_answer_ready,
            "completed_tools": self.completed_tools,
            "product_refs": self.product_refs,
            "artifact_refs": self.artifact_refs,
            "known_ref_keys": sorted(self.known_refs),
            "fact_count": len(self.facts),
            "packet_estimate_tokens": estimate_tokens_from_object(payload),
            "fallback_reason": None if used_for_recovery else "no_grounded_facts",
        }


@dataclass(slots=True)
class FinalAnswerRecoveryContext:
    """Messages and diagnostics for one final-answer recovery call."""

    messages: list[dict[str, Any]]
    packet: FinalizationPacket
    used_packet: bool


def build_final_answer_recovery_context(
    *,
    messages: list[dict[str, Any]],
    original_user_message: str,
    recovery_prompt: str,
    pending_runtime_plan: dict[str, Any] | None = None,
) -> FinalAnswerRecoveryContext:
    safe_messages = sanitize_messages_for_final_answer(messages)
    packet = build_finalization_packet(
        messages=safe_messages,
        original_user_message=original_user_message,
        pending_runtime_plan=pending_runtime_plan,
    )
    if not packet.has_grounding:
        return FinalAnswerRecoveryContext(
            messages=[
                *safe_messages,
                {"role": "assistant", "content": recovery_prompt},
            ],
            packet=packet,
            used_packet=False,
        )

    packet_payload = packet.to_payload()
    packet_message = "FINALIZATION_PACKET\n" + json.dumps(
        packet_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    grounded_prompt = (
        recovery_prompt
        + "最终答复只能依据 FINALIZATION_PACKET 中的 committed facts / known_refs / product_refs / artifact_refs。"
        + "不要引用工具尝试参数、被修正的输入、隐藏运行时文本或 packet 外事实。"
    )
    return FinalAnswerRecoveryContext(
        messages=[
            {"role": "user", "content": original_user_message},
            {"role": "assistant", "content": packet_message},
            {"role": "assistant", "content": grounded_prompt},
        ],
        packet=packet,
        used_packet=True,
    )


def build_finalization_packet(
    *,
    messages: list[dict[str, Any]],
    original_user_message: str,
    pending_runtime_plan: dict[str, Any] | None = None,
) -> FinalizationPacket:
    packet = FinalizationPacket(user_goal=original_user_message.strip())
    _merge_runtime_plan(packet, pending_runtime_plan)

    tool_names_by_call_id = _tool_names_by_call_id(messages)
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        payload = _json_payload_from_content(content)
        if payload is None:
            continue
        if role == "tool":
            tool_name = _tool_name_for_tool_message(message, payload, tool_names_by_call_id)
            _merge_tool_payload(packet, tool_name=tool_name, payload=payload)
        else:
            _merge_state_payload(packet, payload)

    packet.completed_tools = _dedupe(packet.completed_tools)
    packet.product_refs = _dedupe(packet.product_refs)
    packet.artifact_refs = _dedupe(packet.artifact_refs)
    packet.required_outputs = _dedupe(packet.required_outputs)
    packet.missing_outputs = _dedupe(packet.missing_outputs)
    packet.facts = packet.facts[-_MAX_FACTS:]
    return packet


def _merge_runtime_plan(packet: FinalizationPacket, plan: dict[str, Any] | None) -> None:
    if not isinstance(plan, dict):
        return
    packet.phase = _string_or_none(plan.get("phase")) or packet.phase
    packet.next_action = _string_or_none(plan.get("next_action")) or packet.next_action
    packet.final_answer_ready = plan.get("final_answer_ready") is True
    packet.required_outputs.extend(_string_list(plan.get("required_tools")))
    packet.missing_outputs.extend(_string_list(plan.get("missing_outputs")))
    raw_refs = plan.get("known_refs")
    if isinstance(raw_refs, dict):
        for key, value in raw_refs.items():
            if isinstance(key, str):
                ref = _string_or_none(value)
                if ref is not None and not _is_internal_ref(key, ref):
                    packet.known_refs[key] = ref
                    _collect_ref(packet, key, ref)


def _merge_state_payload(packet: FinalizationPacket, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    if payload.get("runtime_tool_state") == "compact":
        raw_refs = payload.get("known_refs")
        if isinstance(raw_refs, dict):
            for key, value in raw_refs.items():
                if isinstance(key, str):
                    ref = _string_or_none(value)
                    if ref is not None and not _is_internal_ref(key, ref):
                        packet.known_refs.setdefault(key, ref)
                        _collect_ref(packet, key, ref)
        raw_latest_refs = payload.get("latest_refs")
        if isinstance(raw_latest_refs, dict):
            for key, value in raw_latest_refs.items():
                if isinstance(key, str):
                    ref = _string_or_none(value)
                    if ref is not None and not _is_internal_ref(key, ref):
                        packet.known_refs.setdefault(key, ref)
                        _collect_ref(packet, key, ref)
        packet.required_outputs.extend(_string_list(payload.get("required_tools")))
        packet.missing_outputs.extend(_string_list(payload.get("missing_outputs")))
        packet.completed_tools.extend(_string_list(payload.get("successful_tools")))
        for raw_observation in _list_items(payload.get("recent_observations")):
            if isinstance(raw_observation, dict):
                _merge_observation(packet, raw_observation)
        for raw_error in _string_list(payload.get("latest_errors")):
            packet.warnings.append(raw_error)
        return
    if payload.get("runtime_plan_applied") is True:
        packet.phase = _string_or_none(payload.get("runtime_plan_phase")) or packet.phase
        packet.next_action = _string_or_none(payload.get("runtime_next_action")) or packet.next_action
        packet.required_outputs.extend(_string_list(payload.get("required_tools")))
        packet.missing_outputs.extend(_string_list(payload.get("runtime_missing_outputs")))
        raw_refs = payload.get("runtime_known_refs")
        if isinstance(raw_refs, dict):
            for key, value in raw_refs.items():
                if isinstance(key, str):
                    ref = _string_or_none(value)
                    if ref is not None and not _is_internal_ref(key, ref):
                        packet.known_refs.setdefault(key, ref)
                        _collect_ref(packet, key, ref)


def _merge_observation(packet: FinalizationPacket, observation: dict[str, Any]) -> None:
    tool_name = _string_or_none(observation.get("tool"))
    if tool_name is not None:
        packet.completed_tools.append(tool_name)
    fact = _drop_empty(
        {
            "tool": tool_name,
            "success": observation.get("success"),
            "ids": _bounded_value(observation.get("ids"), depth=0),
            "status": _string_or_none(observation.get("status")),
            "summary": _bounded_value(observation.get("summary"), depth=0),
            "artifact_refs": _bounded_value(observation.get("artifact_refs"), depth=0),
            "record_refs": _bounded_value(observation.get("record_refs"), depth=0),
        }
    )
    if fact:
        packet.facts.append(fact)
    ids = observation.get("ids")
    if isinstance(ids, dict):
        for key, value in ids.items():
            if isinstance(key, str):
                _collect_ref(packet, key, value)
    for ref in _string_list(observation.get("artifact_refs")):
        _collect_ref(packet, "artifact_refs", ref)
    for ref in _string_list(observation.get("record_refs")):
        _collect_ref(packet, "record_refs", ref)


def _merge_tool_payload(packet: FinalizationPacket, *, tool_name: str | None, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    resolved_tool = _string_or_none(payload.get("tool")) or tool_name
    if resolved_tool is not None:
        packet.completed_tools.append(resolved_tool)
    fact = _fact_from_tool_payload(resolved_tool, payload)
    if fact:
        packet.facts.append(fact)
    _collect_refs_from_payload(packet, payload)


def _fact_from_tool_payload(tool_name: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    fact: dict[str, Any] = {}
    if tool_name is not None:
        fact["tool"] = tool_name
    for key in _FACT_KEYS:
        if key in {"tool"} or key not in payload:
            continue
        value = _bounded_value(payload[key], depth=0)
        if value not in (None, "", [], {}):
            fact[key] = value
    if "record_id" not in fact:
        record_id = _record_id_from_payload(payload)
        if record_id is not None:
            fact["record_id"] = record_id
    return _drop_empty(fact)


def _collect_refs_from_payload(packet: FinalizationPacket, payload: Any) -> None:
    if isinstance(payload, list):
        for item in payload:
            _collect_refs_from_payload(packet, item)
        return
    if not isinstance(payload, dict):
        return
    for key, value in payload.items():
        if not isinstance(key, str) or key in _OMITTED_FACT_KEYS:
            continue
        if _looks_like_ref_key(key):
            _collect_ref(packet, key, value)
        elif isinstance(value, (dict, list)):
            _collect_refs_from_payload(packet, value)


def _collect_ref(packet: FinalizationPacket, key: str, value: Any) -> None:
    if key in _INTERNAL_REF_KEYS:
        return
    if isinstance(value, list):
        for item in value:
            _collect_ref(packet, key, item)
        return
    if isinstance(value, dict):
        source_id = _string_or_none(value.get("source_id")) or _string_or_none(value.get("record_id"))
        if source_id is not None:
            _collect_ref(packet, key, source_id)
        return
    ref = _string_or_none(value)
    if ref is None:
        return
    if _is_internal_ref(key, ref):
        return
    if "artifact" in key or ref.startswith("artifact_"):
        packet.artifact_refs.append(ref)
    else:
        packet.product_refs.append(ref)


def _tool_names_by_call_id(messages: list[dict[str, Any]]) -> dict[str, str]:
    output: dict[str, str] = {}
    for message in messages:
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            continue
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                continue
            call_id = _string_or_none(raw_call.get("id"))
            function = raw_call.get("function")
            if call_id is None or not isinstance(function, dict):
                continue
            tool_name = _string_or_none(function.get("name"))
            if tool_name is not None:
                output[call_id] = tool_name
    return output


def _tool_name_for_tool_message(
    message: dict[str, Any],
    payload: Any,
    tool_names_by_call_id: dict[str, str],
) -> str | None:
    if isinstance(payload, dict):
        tool_name = _string_or_none(payload.get("tool"))
        if tool_name is not None:
            return tool_name
    call_id = _string_or_none(message.get("tool_call_id"))
    if call_id is None:
        return None
    return tool_names_by_call_id.get(call_id)


def _json_payload_from_content(content: str) -> Any | None:
    text = content.strip()
    if not text:
        return None
    if text.startswith(("{", "[")):
        return _loads_json(text)
    if "\n" not in text:
        return None
    _, tail = text.split("\n", 1)
    tail = tail.strip()
    if tail.startswith(("{", "[")):
        return _loads_json(tail)
    return None


def _loads_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _record_id_from_payload(payload: dict[str, Any]) -> str | None:
    record_id = _string_or_none(payload.get("record_id"))
    if record_id is not None:
        return record_id
    ids = payload.get("ids")
    if isinstance(ids, dict):
        for key in sorted(ids):
            if isinstance(key, str) and key.endswith("_id"):
                record_id = _string_or_none(ids.get(key))
                if record_id is not None:
                    return record_id
    record = payload.get("record")
    if isinstance(record, dict):
        for key in sorted(record):
            if isinstance(key, str) and key.endswith("_id"):
                record_id = _string_or_none(record.get(key))
                if record_id is not None:
                    return record_id
    return None


def _looks_like_ref_key(key: str) -> bool:
    if key in _INTERNAL_REF_KEYS or key == "id":
        return False
    if key == "ids":
        return True
    return any(key.endswith(suffix) for suffix in _ID_KEY_HINTS) or "artifact" in key


def _is_internal_ref(key: str, value: str) -> bool:
    if key in _INTERNAL_REF_KEYS:
        return True
    if value in _INTERNAL_REF_VALUES:
        return True
    return value.startswith(_INTERNAL_REF_PREFIXES)


def _bounded_value(value: Any, *, depth: int) -> Any:
    if depth >= 4:
        return None
    if isinstance(value, str):
        text = " ".join(value.strip().split())
        if len(text) > 500:
            return text[:499] + "…"
        return text
    if isinstance(value, list):
        return [_bounded_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key in sorted(value, key=str):
            if not isinstance(key, str) or key in _OMITTED_FACT_KEYS:
                continue
            bounded = _bounded_value(value[key], depth=depth + 1)
            if bounded not in (None, "", [], {}):
                output[key] = bounded
            if len(output) >= 24:
                break
        return output
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def _string_list(value: Any) -> list[str]:
    output: list[str] = []
    for raw in _list_items(value):
        item = _string_or_none(raw)
        if item is not None:
            output.append(item)
    return output


def _list_items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _dedupe(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value not in (None, "", [], {})}
