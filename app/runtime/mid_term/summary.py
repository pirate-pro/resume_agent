"""Model summarization and validation for mid-term flushing."""

from __future__ import annotations

import re
from typing import Any

from app.core.errors import ValidationError
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.prompts.mid_term import MID_TERM_SUMMARIZER_SYSTEM_PROMPT, build_mid_term_user_prompt
from app.runtime.mid_term.models import MidTermEventPack
from app.runtime.mid_term.shared import (
    MAX_LIST_LINES,
    normalize_evidence,
    normalize_score,
    optional_text,
    parse_json_object,
)


class MidTermSummarizer:
    """Summarize event packs into structured sections using model output."""

    def __init__(self, model_client: ChatModelClient) -> None:
        self._model_client = model_client

    def summarize(self, pack: MidTermEventPack) -> dict[str, Any]:
        prompt = build_mid_term_user_prompt(pack)
        response = self._model_client.generate(
            system_prompt=MID_TERM_SUMMARIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[],
        )
        if not isinstance(response, ModelResponse):
            raise ValidationError("summarizer model response type is invalid.")
        text = (response.content or "").strip()
        if not text:
            raise ValidationError("summarizer model returned empty content.")
        payload = parse_json_object(text)
        if not isinstance(payload, dict):
            raise ValidationError("summarizer output is not JSON object.")
        return payload

    async def summarize_async(self, pack: MidTermEventPack) -> dict[str, Any]:
        chunks: list[str] = []
        async for chunk in self._model_client.generate_stream(
            system_prompt=MID_TERM_SUMMARIZER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_mid_term_user_prompt(pack)}],
            tools=[],
        ):
            if not isinstance(chunk, StreamChunk):
                continue
            if chunk.delta:
                chunks.append(chunk.delta)
        payload = parse_json_object("".join(chunks).strip())
        if not isinstance(payload, dict):
            raise ValidationError("summarizer stream output is not JSON object.")
        return payload


class MidTermSummaryValidator:
    """Validate summarizer JSON against schema and evidence constraints."""

    _REQUIRED_KEYS = (
        "active_context",
        "decisions",
        "progress",
        "open_questions",
        "candidate_long_term",
        "artifact_refs",
    )

    def validate(self, summary: dict[str, Any], pack: MidTermEventPack) -> dict[str, Any]:
        for key in self._REQUIRED_KEYS:
            if key not in summary:
                raise ValidationError(f"summarizer output missing key: {key}")
            if not isinstance(summary[key], list):
                raise ValidationError(f"summarizer key '{key}' must be list.")

        event_index = _build_event_index(pack)
        valid_event_ids = set(event_index)
        latest_name, latest_name_event_id = _latest_user_name_signal(pack.events)
        forbidden_memory_signals = _forbidden_memory_signals(pack.events)
        forbidden_memory_event_ids = {item["event_id"] for item in forbidden_memory_signals}

        normalized: dict[str, Any] = {}
        normalized["active_context"] = self._normalize_active_context(summary["active_context"], valid_event_ids)
        normalized["active_context"] = _ensure_forbidden_memory_active_context(
            normalized["active_context"],
            forbidden_memory_signals,
        )
        normalized["decisions"] = self._normalize_decisions(summary["decisions"], valid_event_ids)
        normalized["progress"] = self._normalize_progress(summary["progress"], event_index)
        normalized["open_questions"] = self._normalize_open_questions(summary["open_questions"], valid_event_ids)
        normalized["candidate_long_term"] = self._normalize_candidates(
            summary["candidate_long_term"],
            event_index,
            latest_name=latest_name,
            latest_name_event_id=latest_name_event_id,
            forbidden_memory_event_ids=forbidden_memory_event_ids,
        )
        normalized["artifact_refs"] = self._normalize_artifact_refs(summary["artifact_refs"], valid_event_ids)
        return normalized

    def _normalize_active_context(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            summary = optional_text(raw.get("summary"))
            evidence = _normalize_required_evidence(
                raw.get("evidence_event_ids"),
                valid_event_ids,
                field=f"active_context[{index}].evidence_event_ids",
            )
            if summary is None or not evidence:
                continue
            confidence = normalize_score(raw.get("confidence"), default=0.7)
            output.append({"summary": summary, "evidence_event_ids": evidence, "confidence": confidence})
        return output

    def _normalize_decisions(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            summary = optional_text(raw.get("summary"))
            evidence = _normalize_required_evidence(
                raw.get("evidence_event_ids"),
                valid_event_ids,
                field=f"decisions[{index}].evidence_event_ids",
            )
            if summary is None or not evidence:
                continue
            stability = optional_text(raw.get("stability")) or "tentative"
            output.append({"summary": summary, "evidence_event_ids": evidence, "stability": stability})
        return output

    def _normalize_progress(self, items: list[Any], event_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        valid_event_ids = set(event_index)
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            tool_name = optional_text(raw.get("tool_name"))
            call_summary = optional_text(raw.get("call_summary"))
            result_summary = optional_text(raw.get("result_summary"))
            evidence = _normalize_required_evidence(
                raw.get("evidence_event_ids"),
                valid_event_ids,
                field=f"progress[{index}].evidence_event_ids",
            )
            if tool_name is None or call_summary is None or result_summary is None or not evidence:
                continue
            _require_tool_pair_evidence(evidence, event_index, field=f"progress[{index}].evidence_event_ids")
            success = bool(raw.get("success"))
            output.append(
                {
                    "tool_name": tool_name,
                    "call_summary": call_summary,
                    "result_summary": result_summary,
                    "success": success,
                    "evidence_event_ids": evidence,
                }
            )
        return output

    def _normalize_open_questions(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            question = optional_text(raw.get("question"))
            evidence = _normalize_required_evidence(
                raw.get("evidence_event_ids"),
                valid_event_ids,
                field=f"open_questions[{index}].evidence_event_ids",
            )
            if question is None or not evidence:
                continue
            output.append({"question": question, "evidence_event_ids": evidence})
        return output

    def _normalize_candidates(
        self,
        items: list[Any],
        event_index: dict[str, dict[str, Any]],
        *,
        latest_name: str | None,
        latest_name_event_id: str | None,
        forbidden_memory_event_ids: set[str],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        valid_event_ids = set(event_index)
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            content = optional_text(raw.get("content"))
            why = optional_text(raw.get("why_reusable"))
            evidence = _normalize_candidate_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            tags_raw = raw.get("tags")
            tags = [tag.strip() for tag in tags_raw if isinstance(tag, str) and tag.strip()] if isinstance(tags_raw, list) else []
            if content is None or why is None or not evidence:
                continue
            evidence = _repair_latest_name_candidate_evidence(
                content=content,
                evidence=evidence,
                latest_name=latest_name,
                latest_name_event_id=latest_name_event_id,
                valid_event_ids=valid_event_ids,
            )
            if _is_assistant_only_candidate(evidence=evidence, event_index=event_index):
                continue
            if _is_forbidden_candidate(
                content=content,
                evidence=evidence,
                forbidden_memory_event_ids=forbidden_memory_event_ids,
            ):
                continue
            if _is_outdated_name_candidate(content=content, latest_name=latest_name):
                continue
            if _is_temporary_state_candidate(content=content, tags=tags):
                continue
            confidence = normalize_score(raw.get("confidence"), default=0.7)
            output.append(
                {
                    "content": content,
                    "tags": tags,
                    "confidence": confidence,
                    "why_reusable": why,
                    "evidence_event_ids": evidence,
                }
            )
        return output

    def _normalize_artifact_refs(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, raw in enumerate(items[:MAX_LIST_LINES]):
            if not isinstance(raw, dict):
                continue
            path_or_file_id = optional_text(raw.get("path_or_file_id"))
            reason = optional_text(raw.get("reason"))
            evidence = _normalize_required_evidence(
                raw.get("evidence_event_ids"),
                valid_event_ids,
                field=f"artifact_refs[{index}].evidence_event_ids",
            )
            if path_or_file_id is None or reason is None or not evidence:
                continue
            output.append({"path_or_file_id": path_or_file_id, "reason": reason, "evidence_event_ids": evidence})
        return output


_NAME_PATTERNS = (
    re.compile(r"(?:名字叫|名字是|最新名字是|叫我|称呼我|改名为|叫)(?P<name>[\u4e00-\u9fffA-Za-z0-9_-]{1,24})"),
    re.compile(r"(?P<name>[\u4e00-\u9fffA-Za-z0-9_-]{1,24})(?:才是最新名字|是最新名字)"),
)
_TEMPORARY_STATE_TERMS = (
    "下一步",
    "待办",
    "临时任务",
    "当前任务",
    "本轮",
    "这个 session",
    "这次会话",
)


def _build_event_index(pack: MidTermEventPack) -> dict[str, dict[str, Any]]:
    event_index: dict[str, dict[str, Any]] = {}
    for item in pack.events:
        event_id = str(item.get("event_id", "")).strip()
        if event_id:
            event_index[event_id] = item
    return event_index


def _normalize_required_evidence(raw: Any, valid_event_ids: set[str], *, field: str) -> list[str]:
    if not isinstance(raw, list) or not raw:
        raise ValidationError(f"{field} must contain at least one valid event id.")
    raw_event_ids = [item.strip() for item in raw if isinstance(item, str) and item.strip()]
    if not raw_event_ids:
        raise ValidationError(f"{field} must contain at least one valid event id.")
    invalid = sorted({event_id for event_id in raw_event_ids if event_id not in valid_event_ids})
    if invalid:
        raise ValidationError(f"{field} contains invalid event ids: {','.join(invalid)}")
    return normalize_evidence(raw_event_ids, valid_event_ids)


def _normalize_candidate_evidence(raw: Any, valid_event_ids: set[str]) -> list[str]:
    if not isinstance(raw, list):
        return []
    return normalize_evidence(raw, valid_event_ids)


def _require_tool_pair_evidence(evidence: list[str], event_index: dict[str, dict[str, Any]], *, field: str) -> None:
    observed: dict[str, set[str]] = {}
    for event_id in evidence:
        event = event_index.get(event_id)
        if event is None:
            continue
        event_type = str(event.get("type", "")).strip()
        if event_type not in {"tool_call", "tool_result"}:
            continue
        call_id = _event_tool_call_id(event)
        if not call_id:
            raise ValidationError(f"{field} references tool event without tool_call_id: {event_id}")
        observed.setdefault(call_id, set()).add(event_type)
    for call_id, types in observed.items():
        if types != {"tool_call", "tool_result"}:
            raise ValidationError(f"{field} must include paired tool_call/tool_result for {call_id}.")


def _event_tool_call_id(event: dict[str, Any]) -> str:
    raw = event.get("tool_call_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    payload = event.get("payload")
    if isinstance(payload, dict):
        raw_payload = payload.get("tool_call_id")
        if isinstance(raw_payload, str) and raw_payload.strip():
            return raw_payload.strip()
    return ""


def _is_assistant_only_candidate(*, evidence: list[str], event_index: dict[str, dict[str, Any]]) -> bool:
    evidence_types = {str(event_index[event_id].get("type", "")).strip() for event_id in evidence if event_id in event_index}
    return bool(evidence_types) and evidence_types.issubset({"assistant_message", "assistant_thinking", "run_finished"})


def _is_forbidden_candidate(
    *,
    content: str,
    evidence: list[str],
    forbidden_memory_event_ids: set[str],
) -> bool:
    if not forbidden_memory_event_ids:
        return "临时暗号" in content or "不要记住" in content
    if forbidden_memory_event_ids.intersection(evidence):
        return True
    return "临时暗号" in content or "不要记住" in content


def _is_outdated_name_candidate(*, content: str, latest_name: str | None) -> bool:
    if latest_name is None or latest_name not in content:
        extracted = _extract_name(content)
        if extracted is not None and latest_name is not None:
            return True
    return False


def _is_temporary_state_candidate(*, content: str, tags: list[str]) -> bool:
    lowered_tags = {tag.lower() for tag in tags}
    if lowered_tags.intersection({"short", "session_state", "working_state", "task_state", "temporary"}):
        return True
    return any(term in content for term in _TEMPORARY_STATE_TERMS)


def _repair_latest_name_candidate_evidence(
    *,
    content: str,
    evidence: list[str],
    latest_name: str | None,
    latest_name_event_id: str | None,
    valid_event_ids: set[str],
) -> list[str]:
    if latest_name is None or latest_name_event_id is None:
        return evidence
    if latest_name not in content:
        return evidence
    if latest_name_event_id not in valid_event_ids:
        return evidence
    if latest_name_event_id in evidence:
        return evidence
    return normalize_evidence([latest_name_event_id, *evidence], valid_event_ids)


def _latest_user_name_signal(events: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    latest: str | None = None
    latest_event_id: str | None = None
    for event in events:
        if str(event.get("type", "")).strip() != "user_message":
            continue
        name = _extract_name(_event_text(event))
        if name:
            latest = name
            event_id = str(event.get("event_id", "")).strip()
            latest_event_id = event_id or None
    return latest, latest_event_id


def _extract_name(text: str) -> str | None:
    normalized = text.replace("，", ",").replace("。", ".").replace("：", ":")
    for pattern in _NAME_PATTERNS:
        matched = pattern.search(normalized)
        if matched is None:
            continue
        name = matched.group("name").strip(" ,.:;，。；：")
        if name:
            return name
    return None


def _ensure_forbidden_memory_active_context(
    active_context: list[dict[str, Any]],
    forbidden_memory_signals: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not forbidden_memory_signals:
        return active_context
    output = list(active_context)
    if any("临时暗号" in str(item.get("summary", "")) and "不要记住" in str(item.get("summary", "")) for item in output):
        return output
    seen_evidence = {
        event_id
        for item in output
        for event_id in item.get("evidence_event_ids", [])
        if isinstance(event_id, str)
    }
    for signal in forbidden_memory_signals[:2]:
        event_id = signal["event_id"]
        if event_id in seen_evidence and "不要记住" in signal["text"]:
            pass
        elif event_id in seen_evidence:
            continue
        output.append(
            {
                "summary": f"用户明确声明该临时上下文不要记住/不要写入长期 memory：{signal['text']}",
                "evidence_event_ids": [event_id],
                "confidence": 0.95,
            }
        )
        seen_evidence.add(event_id)
    return output


def _forbidden_memory_signals(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for event in events:
        if str(event.get("type", "")).strip() != "user_message":
            continue
        text = _event_text(event)
        if "不要记住" in text or "不要写入 memory" in text or "不要写入memory" in text:
            event_id = str(event.get("event_id", "")).strip()
            if event_id:
                output.append({"event_id": event_id, "text": text[:240]})
    return output


def _event_text(event: dict[str, Any]) -> str:
    raw = event.get("text")
    if isinstance(raw, str):
        return raw
    payload = event.get("payload")
    if isinstance(payload, dict):
        content = payload.get("content")
        if isinstance(content, str):
            return content
    return ""
