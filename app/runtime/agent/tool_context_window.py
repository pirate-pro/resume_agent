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
    "sanitize_messages_for_final_answer",
]

_VALID_MODES = {"off", "compact"}
_DEFAULT_MAX_OBSERVATIONS = 10
_DEFAULT_DETAILED_OBSERVATIONS = 4
_DEFAULT_MAX_STATE_CHARS = 1800
_MAX_REVEALED_TOOL_NAMES = 32
_TEXT_LIMIT = 180
_FAILED_CONTENT_PREVIEW_CHARS = 220
_LONG_CONTENT_ARGUMENT_CHARS = 480
_FINAL_ANSWER_OMITTED_KEYS = {
    "arguments",
    "content",
    "content_omitted",
    "content_preview",
    "source_alignment_repairs",
    "updates",
}
_STRICT_REQUIRED_TOOL_SUPPORTING_TOOLS = {
    "career_application_merge": {"career_resume_version_create"},
    "career_resume_version_create": {
        "career_application_get",
        "career_resume_profile_get",
        "career_jd_analysis_get",
        "career_job_fit_report_get",
    },
    "career_job_fit_report_save": {
        "session_create_text_artifact",
        "career_jd_analysis_save",
    },
    "session_create_text_artifact": {
        "session_read_artifact",
        "career_resume_profile_get",
        "career_profile_get",
        "career_jd_analysis_save",
        "career_jd_analysis_get",
    },
    "career_resume_profile_save": {
        "session_create_text_artifact",
        "session_read_artifact",
    },
}
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

    def render_messages(
        self,
        *,
        runtime_plan: dict[str, Any] | None = None,
        strict_mode: bool = False,
    ) -> list[dict[str, Any]]:
        messages = list(self._base_messages)
        if self._mode == "off":
            messages.extend(self._history_messages)
        else:
            state_message = self._state_message(runtime_plan=runtime_plan, strict_mode=strict_mode)
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
        replay_assistant_message = assistant_message
        if self._mode == "compact":
            replay_assistant_message = _compact_assistant_tool_call_message(assistant_message, observations)
        self._pending_exchange = ToolExchange(
            assistant_message=replay_assistant_message,
            tool_messages=list(tool_messages),
            observations=list(observations),
        )

    def append_runtime_notice(self, content: str) -> None:
        """Append a small runtime guard notice to the next model round."""

        text = content.strip()
        if not text:
            return
        self._base_messages.append({"role": "assistant", "content": text})

    def usage_payload(
        self,
        *,
        runtime_plan: dict[str, Any] | None = None,
        strict_mode: bool = False,
    ) -> dict[str, Any]:
        state_message = self._state_message(runtime_plan=runtime_plan, strict_mode=strict_mode)
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

    def _state_message(
        self,
        *,
        runtime_plan: dict[str, Any] | None = None,
        strict_mode: bool = False,
    ) -> dict[str, str] | None:
        if self._mode != "compact" or not self._observations:
            return None
        payload = self._state_payload(runtime_plan=runtime_plan, strict_mode=strict_mode)
        content = _dump_bounded(payload, max_chars=self._max_state_chars)
        return {
            "role": "assistant",
            "content": f"运行时工具状态摘要（完整工具结果见事件日志）：\n{content}",
        }

    def _state_payload(
        self,
        *,
        runtime_plan: dict[str, Any] | None = None,
        strict_mode: bool = False,
    ) -> dict[str, Any]:
        observations = _strict_runtime_observations(
            self._observations,
            runtime_plan=runtime_plan,
            strict_mode=strict_mode,
        )
        observations = observations[-self._max_observations :]
        detailed_observations = observations[-_DEFAULT_DETAILED_OBSERVATIONS:]
        older_observations = observations[: -_DEFAULT_DETAILED_OBSERVATIONS]
        plan_known_refs = _runtime_plan_known_refs(runtime_plan)
        latest_refs = _latest_refs(observations)
        latest_refs.update(plan_known_refs)
        revealed_tool_names = _latest_revealed_tool_names(observations)
        revealed_tool_groups = _revealed_tool_groups(revealed_tool_names)
        latest_errors = [
            observation.error
            for observation in reversed(observations)
            if observation.error
        ][:3]
        successful_tools = _dedupe(
            [observation.tool_name for observation in observations if observation.success]
        )[-12:]
        strict_required_tools = _runtime_plan_tool_names((runtime_plan or {}).get("required_tools"))
        return _drop_empty(
            {
                "runtime_tool_state": "compact",
                "strict_runtime_plan": True if strict_mode and runtime_plan is not None else None,
                "tool_call_count": len(self._observations),
                "shown_tool_call_count": len(observations)
                if strict_mode and len(observations) != len(self._observations)
                else None,
                "required_tools": strict_required_tools,
                "known_refs": plan_known_refs,
                "missing_outputs": _runtime_plan_tool_names((runtime_plan or {}).get("missing_outputs")),
                "discouraged_tools": _strict_discouraged_tools(runtime_plan) if strict_mode else [],
                "successful_tools": successful_tools,
                "tool_search_guidance": _tool_search_guidance(revealed_tool_names),
                "revealed_tool_names": revealed_tool_names,
                "revealed_tool_groups": revealed_tool_groups,
                "workflow_completion_guidance": _workflow_completion_guidance(observations),
                "latest_refs": latest_refs,
                "older_observation_summary": _older_observation_summary(older_observations),
                "recent_observations": [observation.to_payload() for observation in detailed_observations],
                "latest_errors": list(reversed(latest_errors)),
            }
        )


def normalize_tool_context_window_mode(value: str) -> str:
    normalized = value.strip().lower()
    return normalized if normalized in _VALID_MODES else "off"


def sanitize_messages_for_final_answer(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove model-attempt facts from messages before final-answer recovery.

    Tool-loop messages intentionally carry compact arguments so the model can
    repair a failed call. Final answers must instead rely on committed tool
    results and records, not raw or repaired input arguments.
    """

    return [_sanitize_final_answer_message(message) for message in messages]


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
        if payload.get("workflow_runtime_result") is True:
            return _workflow_runtime_summary(payload)
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


def _sanitize_final_answer_message(message: dict[str, Any]) -> dict[str, Any]:
    output = dict(message)
    tool_calls = output.get("tool_calls")
    if isinstance(tool_calls, list):
        sanitized_calls: list[Any] = []
        for raw_call in tool_calls:
            if not isinstance(raw_call, dict):
                sanitized_calls.append(raw_call)
                continue
            call = dict(raw_call)
            function = call.get("function")
            if isinstance(function, dict):
                function_copy = dict(function)
                function_copy["arguments"] = "{}"
                call["function"] = function_copy
            sanitized_calls.append(call)
        output["tool_calls"] = sanitized_calls
    content = output.get("content")
    if isinstance(content, str):
        output["content"] = _sanitize_final_answer_content(content)
    return output


def _sanitize_final_answer_content(content: str) -> str:
    prefix, payload_text = _split_json_payload(content)
    if payload_text is None:
        return content
    payload = _loads_json(payload_text)
    if payload is None:
        return content
    sanitized = _sanitize_final_answer_payload(payload)
    dumped = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"))
    return f"{prefix}{dumped}" if prefix else dumped


def _split_json_payload(content: str) -> tuple[str, str | None]:
    stripped = content.strip()
    if stripped.startswith(("{", "[")):
        return "", stripped
    if "\n" not in content:
        return content, None
    prefix, payload = content.split("\n", 1)
    if payload.strip().startswith(("{", "[")):
        return f"{prefix}\n", payload.strip()
    return content, None


def _sanitize_final_answer_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_sanitize_final_answer_payload(item) for item in payload]
    if not isinstance(payload, dict):
        return payload
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        if key in _FINAL_ANSWER_OMITTED_KEYS:
            if key == "source_alignment_repairs":
                output["source_alignment_repaired"] = True
            continue
        output[key] = _sanitize_final_answer_payload(value)
    return output


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
    runtime_guidance = _latest_runtime_guidance(observations)
    if runtime_guidance is not None:
        hints.append(runtime_guidance)
    if "session_create_text_artifact" in successful_tools:
        hints.append(
            "当前 run 已成功创建文本 artifact；如果它就是本任务目标文件，请复用最新 artifact_id，不要为同一标题/内容重复创建。"
        )
    if "career_jd_analysis_save" in successful_tools:
        hints.append("JDAnalysis 已在本 run 成功保存；后续保存 JobFitReport 时复用该 jd_analysis_id，不要重复保存同一份 JD 分析。")
    if "career_job_fit_report_save" in successful_tools:
        hints.append("JobFitReport 已在本 run 成功保存；如果报告 artifact 已存在，下一步应汇总结果，不要重新保存匹配报告。")
    if {"career_jd_analysis_save", "career_job_fit_report_save"} <= successful_tools:
        hints.append("JDAnalysis 和 JobFitReport 已在本 run 成功保存；不要重复保存同一份 JD 分析或匹配报告。")
    if "career_resume_version_create" in successful_tools:
        hints.append("ResumeVersion 已在本 run 成功创建；除非用户明确要求另一版，否则不要再次创建 ResumeVersion。")
    if {"career_resume_version_create", "career_application_merge"} <= successful_tools:
        hints.append("定制简历已创建并已合并进 CareerApplication；下一步应给最终答复，不要重新读取全部关联记录。")
    return hints


def _strict_runtime_observations(
    observations: list[ToolObservation],
    *,
    runtime_plan: dict[str, Any] | None,
    strict_mode: bool,
) -> list[ToolObservation]:
    if not strict_mode or runtime_plan is None:
        return list(observations)
    required_tools = _runtime_plan_tool_names(runtime_plan.get("required_tools"))
    if not required_tools:
        required_tools = _runtime_plan_tool_names(runtime_plan.get("next_allowed_tools"))
    if len(required_tools) != 1:
        return list(observations)
    required_tool = required_tools[0]
    supporting_tools = {required_tool, *_STRICT_REQUIRED_TOOL_SUPPORTING_TOOLS.get(required_tool, set())}
    discouraged_tools = set(_strict_discouraged_tools(runtime_plan))
    filtered: list[ToolObservation] = []
    for observation in observations:
        if observation.tool_name in supporting_tools:
            filtered.append(observation)
            continue
        if observation.tool_name not in discouraged_tools:
            filtered.append(observation)
    return filtered


def _strict_discouraged_tools(runtime_plan: dict[str, Any] | None) -> list[str]:
    if runtime_plan is None:
        return []
    names = [
        *_runtime_plan_tool_names(runtime_plan.get("discouraged_tools")),
        *_runtime_plan_tool_names(runtime_plan.get("blocked_tools")),
        *_runtime_plan_tool_names(runtime_plan.get("blocked_actions")),
        "tool_search",
    ]
    return [name for name in _dedupe(names) if name]


def _runtime_plan_tool_names(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            output.append(item.strip())
    return output


def _runtime_plan_known_refs(runtime_plan: dict[str, Any] | None) -> dict[str, Any]:
    if runtime_plan is None:
        return {}
    raw_refs = runtime_plan.get("known_refs")
    if not isinstance(raw_refs, dict):
        return {}
    return {str(key): value for key, value in raw_refs.items() if isinstance(key, str) and value is not None}


def _workflow_runtime_summary(payload: dict[str, Any]) -> str:
    policy = payload.get("policy")
    reason = payload.get("reason")
    next_action = payload.get("next_action")
    missing_outputs = payload.get("missing_outputs")
    parts = ["WorkflowRuntime", str(policy or "decision")]
    if isinstance(reason, str) and reason.strip():
        parts.append(reason.strip())
    if isinstance(next_action, str) and next_action.strip():
        parts.append(f"下一步：{next_action.strip()}")
    if isinstance(missing_outputs, list) and missing_outputs:
        parts.append(f"缺失产物：{', '.join(str(item) for item in missing_outputs[:5])}")
    return _truncate("；".join(parts), _TEXT_LIMIT)


def _latest_runtime_guidance(observations: list[ToolObservation]) -> str | None:
    for observation in reversed(observations):
        if not observation.summary or "WorkflowRuntime" not in observation.summary:
            continue
        if "下一步：" not in observation.summary:
            continue
        return observation.summary
    return None


def _compact_assistant_tool_call_message(
    assistant_message: dict[str, Any],
    observations: list[ToolObservation],
) -> dict[str, Any]:
    raw_tool_calls = assistant_message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return dict(assistant_message)
    observation_by_call_id = {
        observation.tool_call_id: observation
        for observation in observations
        if observation.tool_call_id
    }
    compacted_tool_calls: list[Any] = []
    changed = False
    for raw_call in raw_tool_calls:
        if not isinstance(raw_call, dict):
            compacted_tool_calls.append(raw_call)
            continue
        call_copy = dict(raw_call)
        function = raw_call.get("function")
        if not isinstance(function, dict):
            compacted_tool_calls.append(call_copy)
            continue
        function_copy = dict(function)
        tool_call_id = raw_call.get("id")
        observation = observation_by_call_id.get(tool_call_id) if isinstance(tool_call_id, str) else None
        if observation is not None:
            raw_arguments = function.get("arguments")
            parsed_arguments = _loads_json(raw_arguments) if isinstance(raw_arguments, str) else None
            should_compact = observation.success or _has_long_content_argument(parsed_arguments)
            if should_compact and isinstance(parsed_arguments, dict):
                compacted_arguments = _compact_arguments(
                    parsed_arguments,
                    content_preview_chars=0 if observation.success else _FAILED_CONTENT_PREVIEW_CHARS,
                )
                function_copy["arguments"] = json.dumps(
                    compacted_arguments,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                changed = True
        call_copy["function"] = function_copy
        compacted_tool_calls.append(call_copy)
    if not changed:
        return dict(assistant_message)
    output = dict(assistant_message)
    output["tool_calls"] = compacted_tool_calls
    return output


def _older_observation_summary(observations: list[ToolObservation]) -> dict[str, Any]:
    if not observations:
        return {}
    counts: dict[str, int] = {}
    failed_tools: list[str] = []
    for observation in observations:
        counts[observation.tool_name] = counts.get(observation.tool_name, 0) + 1
        if not observation.success and observation.tool_name not in failed_tools:
            failed_tools.append(observation.tool_name)
    return _drop_empty(
        {
            "count": len(observations),
            "tool_counts": counts,
            "failed_tools": failed_tools[:6],
        }
    )


def _compact_arguments(arguments: dict[str, Any], *, content_preview_chars: int = 0) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in arguments.items():
        if not isinstance(key, str):
            continue
        if key == "content" and isinstance(value, str):
            output["content_omitted"] = {"chars": len(value)}
            if content_preview_chars > 0:
                output["content_preview"] = _truncate(value, content_preview_chars)
            continue
        output[key] = _compact_value(value, text_chars=120, depth=0)
        if len(output) >= 12:
            break
    return output


def _has_long_content_argument(arguments: Any) -> bool:
    return isinstance(arguments, dict) and isinstance(arguments.get("content"), str) and len(arguments["content"]) > _LONG_CONTENT_ARGUMENT_CHARS


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
