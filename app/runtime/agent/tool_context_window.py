"""Model message window for tool-call exchanges within one agent run."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import ToolCall, ToolExecutionResult
from app.runtime.context_compaction.text_utils import estimate_tokens_from_object

__all__ = [
    "ToolContextWindow",
    "ToolExchange",
    "ToolObservation",
    "build_tool_observation",
    "normalize_tool_context_window_mode",
]

_VALID_MODES = {"off", "compact"}
_DEFAULT_MAX_OBSERVATIONS = 12
_DEFAULT_MAX_STATE_CHARS = 2500
_MAX_REVEALED_TOOL_NAMES = 32
_TEXT_LIMIT = 180
_ID_PREFIX_RE = re.compile(
    r"^(artifact|resume_profile|career_profile|jd|fit|resume_version|application|note|learning_task|learning_plan|weakness|checkin|task_group|task)_[A-Za-z0-9_-]+$"
)
_ID_KEYS = {
    "artifact_id",
    "artifact_ids",
    "artifact_refs",
    "base_resume_profile_id",
    "career_profile_id",
    "checkin_id",
    "collection_id",
    "evidence_refs",
    "job_fit_report_id",
    "jd_analysis_id",
    "learning_plan_id",
    "learning_task_id",
    "note_id",
    "record_id",
    "resume_profile_id",
    "resume_version_id",
    "resume_version_ids",
    "source_artifact_id",
    "source_id",
    "target_jd_analysis_id",
    "task_group_id",
    "task_id",
}


@dataclass(frozen=True, slots=True)
class ToolObservation:
    """Small deterministic summary for one executed tool call."""

    tool_name: str
    success: bool
    tool_call_id: str | None
    arguments_preview: dict[str, Any] = field(default_factory=dict)
    ids: dict[str, Any] = field(default_factory=dict)
    status: str | None = None
    summary: str | None = None
    error: str | None = None
    artifact_refs: list[str] = field(default_factory=list)
    record_refs: list[str] = field(default_factory=list)
    revealed_tool_names: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "tool": self.tool_name,
                "success": self.success,
                "tool_call_id": self.tool_call_id,
                "arguments": self.arguments_preview,
                "ids": self.ids,
                "status": self.status,
                "summary": self.summary,
                "error": self.error,
                "artifact_refs": self.artifact_refs,
                "record_refs": self.record_refs,
                "revealed_tool_names": self.revealed_tool_names,
            }
        )


@dataclass(frozen=True, slots=True)
class ToolExchange:
    """One protocol-valid assistant tool_call message plus tool result messages."""

    assistant_message: dict[str, Any]
    tool_messages: list[dict[str, Any]]
    observations: list[ToolObservation]

    def messages(self) -> list[dict[str, Any]]:
        return [self.assistant_message, *self.tool_messages]


class ToolContextWindow:
    """Keep only the latest tool exchange and compact consumed exchanges."""

    def __init__(
        self,
        *,
        base_messages: list[dict[str, Any]],
        mode: str = "off",
        max_observations: int = _DEFAULT_MAX_OBSERVATIONS,
        max_state_chars: int = _DEFAULT_MAX_STATE_CHARS,
    ) -> None:
        self._base_messages = list(base_messages)
        self._mode = normalize_tool_context_window_mode(mode)
        self._max_observations = max(1, max_observations)
        self._max_state_chars = max(600, max_state_chars)
        self._history_messages: list[dict[str, Any]] = []
        self._observations: list[ToolObservation] = []
        self._pending_exchange: ToolExchange | None = None

    @property
    def mode(self) -> str:
        return self._mode

    def render_messages(self) -> list[dict[str, Any]]:
        messages = list(self._base_messages)
        if self._mode == "off":
            messages.extend(self._history_messages)
        else:
            state_message = self._state_message()
            if state_message is not None:
                messages.append(state_message)
        if self._pending_exchange is not None:
            messages.extend(self._pending_exchange.messages())
        return messages

    def consume_pending_exchange(self) -> None:
        if self._pending_exchange is None:
            return
        if self._mode == "off":
            self._history_messages.extend(self._pending_exchange.messages())
        else:
            self._observations.extend(self._pending_exchange.observations)
            if len(self._observations) > self._max_observations * 3:
                self._observations = self._observations[-self._max_observations * 3 :]
        self._pending_exchange = None

    def set_pending_exchange(
        self,
        *,
        assistant_message: dict[str, Any],
        tool_messages: list[dict[str, Any]],
        observations: list[ToolObservation],
    ) -> None:
        self._pending_exchange = ToolExchange(
            assistant_message=assistant_message,
            tool_messages=list(tool_messages),
            observations=list(observations),
        )

    def usage_payload(self) -> dict[str, Any]:
        state_message = self._state_message()
        pending_messages = self._pending_exchange.messages() if self._pending_exchange is not None else []
        return {
            "tool_context_window_mode": self._mode,
            "pending_tool_exchange_count": 1 if self._pending_exchange is not None else 0,
            "pending_tool_message_count": len(pending_messages),
            "compacted_tool_observation_count": len(self._observations) if self._mode == "compact" else 0,
            "tool_state_message_estimate_tokens": estimate_tokens_from_object(state_message) if state_message else 0,
            "tool_pending_message_estimate_tokens": estimate_tokens_from_object(pending_messages)
            if pending_messages
            else 0,
        }

    def _state_message(self) -> dict[str, str] | None:
        if self._mode != "compact" or not self._observations:
            return None
        payload = self._state_payload()
        content = _dump_bounded(payload, max_chars=self._max_state_chars)
        return {
            "role": "assistant",
            "content": f"运行时工具状态摘要（完整工具结果见事件日志）：\n{content}",
        }

    def _state_payload(self) -> dict[str, Any]:
        observations = self._observations[-self._max_observations :]
        latest_refs = _latest_refs(self._observations)
        revealed_tool_names = _latest_revealed_tool_names(self._observations)
        revealed_tool_groups = _revealed_tool_groups(revealed_tool_names)
        latest_errors = [
            observation.error
            for observation in reversed(self._observations)
            if observation.error
        ][:3]
        successful_tools = _dedupe(
            [observation.tool_name for observation in self._observations if observation.success]
        )[-12:]
        return _drop_empty(
            {
                "runtime_tool_state": "compact",
                "tool_call_count": len(self._observations),
                "successful_tools": successful_tools,
                "tool_search_guidance": _tool_search_guidance(revealed_tool_names),
                "revealed_tool_names": revealed_tool_names,
                "revealed_tool_groups": revealed_tool_groups,
                "workflow_completion_guidance": _workflow_completion_guidance(self._observations),
                "latest_refs": latest_refs,
                "observations": [observation.to_payload() for observation in observations],
                "latest_errors": list(reversed(latest_errors)),
            }
        )


def normalize_tool_context_window_mode(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in _VALID_MODES else "off"


def build_tool_observation(
    *,
    tool_call: ToolCall,
    result: ToolExecutionResult,
    model_visible_content: str,
) -> ToolObservation:
    payload = _loads_json(model_visible_content)
    ids = _collect_ids(payload)
    artifact_refs, record_refs = _split_refs(ids)
    revealed_tool_names = _string_list(_payload_get(payload, "revealed_tool_names"), limit=20)
    status = _status_from_payload(payload)
    error = _error_from_payload(payload, fallback_content=model_visible_content) if not result.success else None
    return ToolObservation(
        tool_name=result.tool_name or tool_call.name,
        success=result.success,
        tool_call_id=tool_call.tool_call_id,
        arguments_preview=_compact_arguments(tool_call.arguments),
        ids=ids,
        status=status,
        summary=_summary_for_payload(
            tool_name=result.tool_name or tool_call.name,
            success=result.success,
            payload=payload,
            content=model_visible_content,
        ),
        error=error,
        artifact_refs=artifact_refs,
        record_refs=record_refs,
        revealed_tool_names=revealed_tool_names,
    )


def _summary_for_payload(*, tool_name: str, success: bool, payload: Any, content: str) -> str:
    if not success:
        return _truncate(_error_from_payload(payload, fallback_content=content) or f"{tool_name} failed", _TEXT_LIMIT)
    if isinstance(payload, dict):
        if tool_name == "tool_search":
            groups = _string_list(payload.get("matched_groups"), limit=8)
            count = payload.get("revealed_tool_count")
            return _truncate(f"tool_search revealed {count} tools for groups={groups}", _TEXT_LIMIT)
        record_type = payload.get("record_type")
        if isinstance(record_type, str):
            records = payload.get("records")
            if isinstance(records, list):
                return _truncate(f"{record_type} list returned {len(records)} records", _TEXT_LIMIT)
            record_id = payload.get("record_id")
            found = payload.get("found")
            status = payload.get("status")
            return _truncate(f"{record_type} {record_id or ''} found={found} status={status}", _TEXT_LIMIT)
        if tool_name in {"retrieval_search", "retrieval_context_pack"}:
            count = payload.get("count")
            hit_count = len(_payload_hits(payload))
            context_chars = payload.get("context_char_count")
            return _truncate(f"retrieval returned count={count or hit_count}, context_chars={context_chars}", _TEXT_LIMIT)
        if tool_name in {"delegate_agents", "agent_task_status"}:
            status = payload.get("status")
            results = payload.get("results")
            result_count = len(results) if isinstance(results, list) else 0
            return _truncate(f"delegation status={status}, results={result_count}", _TEXT_LIMIT)
        message = payload.get("message") or payload.get("summary")
        if isinstance(message, str) and message.strip():
            return _truncate(message, _TEXT_LIMIT)
    return _truncate(content, _TEXT_LIMIT)


def _latest_revealed_tool_names(observations: list[ToolObservation]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for observation in reversed(observations):
        for name in reversed(observation.revealed_tool_names):
            if name in seen:
                continue
            output.append(name)
            seen.add(name)
            if len(output) >= _MAX_REVEALED_TOOL_NAMES:
                return list(reversed(output))
    return list(reversed(output))


def _revealed_tool_groups(tool_names: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for name in tool_names:
        group = _tool_group_for_name(name)
        if group == "other" or group in seen:
            continue
        output.append(group)
        seen.add(group)
    return output


def _tool_search_guidance(revealed_tool_names: list[str]) -> str | None:
    if not revealed_tool_names:
        return None
    return "已在 revealed_tool_names 中的工具可以直接调用；不要为了这些工具再次调用 tool_search，只有缺少新能力时再搜索。"


def _tool_group_for_name(name: str) -> str:
    if name.startswith("session_") or name.startswith("workspace_") or name == "publish_artifact":
        return "artifact"
    if name.startswith("retrieval_"):
        return "retrieval"
    if name.startswith("career_"):
        return "career"
    if name.startswith("note_"):
        return "note"
    if name.startswith("learning_"):
        return "learning"
    if name.startswith("memory_"):
        return "memory"
    if name in {"delegate_agents", "agent_task_status"}:
        return "delegation"
    if name.startswith("state_"):
        return "state"
    return "other"


def _workflow_completion_guidance(observations: list[ToolObservation]) -> list[str]:
    successful_tools = {observation.tool_name for observation in observations if observation.success}
    hints: list[str] = []
    if {"career_jd_analysis_save", "career_job_fit_report_save"} <= successful_tools:
        hints.append("JDAnalysis 和 JobFitReport 已在本 run 成功保存；不要重复保存同一份 JD 分析或匹配报告。")
    if "career_resume_version_create" in successful_tools:
        hints.append("ResumeVersion 已在本 run 成功创建；除非用户明确要求另一版，否则不要再次创建 ResumeVersion。")
    if {"career_resume_version_create", "career_application_merge"} <= successful_tools:
        hints.append("定制简历已创建并已合并进 CareerApplication；下一步应给最终答复，不要重新读取全部关联记录。")
    return hints


def _compact_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(key, str):
            continue
        if key == "content" and isinstance(value, str):
            output["content_chars"] = len(value)
            continue
        output[key] = _compact_value(value, text_chars=120, depth=0)
        if len(output) >= 12:
            break
    return output


def _collect_ids(payload: Any) -> dict[str, Any]:
    collected: dict[str, list[Any]] = {}

    def visit(value: Any, *, key: str | None = None, depth: int = 0) -> None:
        if depth > 5:
            return
        if isinstance(value, dict):
            for raw_key, item in value.items():
                if not isinstance(raw_key, str):
                    continue
                normalized_key = raw_key.strip()
                if _is_id_key(normalized_key):
                    _add_id_value(collected, normalized_key, item)
                visit(item, key=normalized_key, depth=depth + 1)
            return
        if isinstance(value, list):
            for item in value[:20]:
                visit(item, key=key, depth=depth + 1)
            return
        if isinstance(value, str) and _looks_like_ref(value):
            _add_id_value(collected, key or "refs", value)

    visit(payload)
    output: dict[str, Any] = {}
    for key, values in collected.items():
        deduped = _dedupe([_compact_value(item, text_chars=160, depth=0) for item in values])
        if not deduped:
            continue
        output[key] = deduped[0] if len(deduped) == 1 else deduped[:10]
    return output


def _add_id_value(target: dict[str, list[Any]], key: str, value: Any) -> None:
    values = target.setdefault(key, [])
    if isinstance(value, list):
        for item in value[:20]:
            if isinstance(item, str) and item.strip():
                values.append(item.strip())
        return
    if isinstance(value, str) and value.strip():
        values.append(value.strip())
    elif isinstance(value, int):
        values.append(value)


def _split_refs(ids: dict[str, Any]) -> tuple[list[str], list[str]]:
    artifacts: list[str] = []
    records: list[str] = []
    for value in ids.values():
        values = value if isinstance(value, list) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            if item.startswith("artifact_"):
                artifacts.append(item)
            elif _looks_like_ref(item):
                records.append(item)
    return _dedupe(artifacts)[:12], _dedupe(records)[:20]


def _latest_refs(observations: list[ToolObservation]) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    artifact_ids: list[str] = []
    for observation in observations:
        for key, value in observation.ids.items():
            if key in {"artifact_id", "artifact_ids", "artifact_refs", "source_artifact_id"}:
                values = value if isinstance(value, list) else [value]
                artifact_ids.extend(item for item in values if isinstance(item, str) and item.startswith("artifact_"))
                continue
            if key.endswith("_id") or key.endswith("_ids") or key == "record_id":
                latest[key] = value
        artifact_ids.extend(observation.artifact_refs)
    if artifact_ids:
        latest["artifact_ids"] = _dedupe(artifact_ids)[-12:]
    return latest


def _status_from_payload(payload: Any) -> str | None:
    status = _payload_get(payload, "status")
    return status if isinstance(status, str) else None


def _error_from_payload(payload: Any, *, fallback_content: str) -> str | None:
    if isinstance(payload, dict):
        for key in ("error", "message", "error_type"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return _truncate(value, _TEXT_LIMIT)
    return _truncate(fallback_content, _TEXT_LIMIT)


def _payload_get(payload: Any, key: str) -> Any:
    return payload.get(key) if isinstance(payload, dict) else None


def _payload_hits(payload: Any) -> list[Any]:
    if not isinstance(payload, dict):
        return []
    hits = payload.get("hits")
    if isinstance(hits, list):
        return hits
    context_pack = payload.get("context_pack")
    if isinstance(context_pack, dict):
        context_hits = context_pack.get("hits")
        if isinstance(context_hits, list):
            return context_hits
    top_hits = payload.get("top_hits")
    return top_hits if isinstance(top_hits, list) else []


def _loads_json(content: str) -> Any | None:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def _dump_bounded(payload: dict[str, Any], *, max_chars: int) -> str:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(content) <= max_chars:
        return content
    reduced = dict(payload)
    observations = reduced.get("observations")
    if isinstance(observations, list):
        reduced["observations"] = observations[-6:]
    content = json.dumps(_shorten_strings(reduced, 120), ensure_ascii=False, separators=(",", ":"))
    if len(content) <= max_chars:
        return content
    fallback = {
        "runtime_tool_state": "compact",
        "tool_call_count": payload.get("tool_call_count"),
        "successful_tools": payload.get("successful_tools"),
        "tool_search_guidance": payload.get("tool_search_guidance"),
        "revealed_tool_names": payload.get("revealed_tool_names"),
        "revealed_tool_groups": payload.get("revealed_tool_groups"),
        "workflow_completion_guidance": payload.get("workflow_completion_guidance"),
        "latest_refs": payload.get("latest_refs"),
        "latest_errors": payload.get("latest_errors"),
        "truncated": True,
    }
    return json.dumps(_drop_empty(fallback), ensure_ascii=False, separators=(",", ":"))[:max_chars]


def _compact_value(value: Any, *, text_chars: int, depth: int) -> Any:
    if isinstance(value, str):
        return _truncate(value, text_chars)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item, text_chars=text_chars, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        if depth >= 2:
            return _truncate(json.dumps(value, ensure_ascii=False, separators=(",", ":")), text_chars)
        return {
            str(key): _compact_value(item, text_chars=text_chars, depth=depth + 1)
            for key, item in list(value.items())[:8]
            if isinstance(key, str)
        }
    return _truncate(str(value), text_chars)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_truncate(item.strip(), 80) for item in value[:limit] if isinstance(item, str) and item.strip()]


def _is_id_key(key: str) -> bool:
    return key in _ID_KEYS or key.endswith("_id") or key.endswith("_ids")


def _looks_like_ref(value: str) -> bool:
    return bool(_ID_PREFIX_RE.match(value.strip()))


def _drop_empty(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != {} and value != []}


def _shorten_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(value, limit)
    if isinstance(value, list):
        return [_shorten_strings(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _shorten_strings(item, limit) for key, item in value.items()}
    return value


def _dedupe(items: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for item in items:
        marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, dict | list) else str(item)
        if marker in seen:
            continue
        output.append(item)
        seen.add(marker)
    return output


def _truncate(text: str, limit: int) -> str:
    normalized = " ".join(str(text).strip().split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 1:
        return normalized[:limit]
    return f"{normalized[: limit - 1]}…"
