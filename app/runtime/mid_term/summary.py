"""Model summarization and validation for mid-term flushing."""

from __future__ import annotations

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

        valid_event_ids = {str(item.get("event_id", "")).strip() for item in pack.events}
        if "" in valid_event_ids:
            valid_event_ids.remove("")

        normalized: dict[str, Any] = {}
        normalized["active_context"] = self._normalize_active_context(summary["active_context"], valid_event_ids)
        normalized["decisions"] = self._normalize_decisions(summary["decisions"], valid_event_ids)
        normalized["progress"] = self._normalize_progress(summary["progress"], valid_event_ids)
        normalized["open_questions"] = self._normalize_open_questions(summary["open_questions"], valid_event_ids)
        normalized["candidate_long_term"] = self._normalize_candidates(summary["candidate_long_term"], valid_event_ids)
        normalized["artifact_refs"] = self._normalize_artifact_refs(summary["artifact_refs"], valid_event_ids)
        return normalized

    def _normalize_active_context(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            summary = optional_text(raw.get("summary"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if summary is None or not evidence:
                continue
            confidence = normalize_score(raw.get("confidence"), default=0.7)
            output.append({"summary": summary, "evidence_event_ids": evidence, "confidence": confidence})
        return output

    def _normalize_decisions(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            summary = optional_text(raw.get("summary"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if summary is None or not evidence:
                continue
            stability = optional_text(raw.get("stability")) or "tentative"
            output.append({"summary": summary, "evidence_event_ids": evidence, "stability": stability})
        return output

    def _normalize_progress(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            tool_name = optional_text(raw.get("tool_name"))
            call_summary = optional_text(raw.get("call_summary"))
            result_summary = optional_text(raw.get("result_summary"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if tool_name is None or call_summary is None or result_summary is None or not evidence:
                continue
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
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            question = optional_text(raw.get("question"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if question is None or not evidence:
                continue
            output.append({"question": question, "evidence_event_ids": evidence})
        return output

    def _normalize_candidates(self, items: list[Any], valid_event_ids: set[str]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            content = optional_text(raw.get("content"))
            why = optional_text(raw.get("why_reusable"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            tags_raw = raw.get("tags")
            tags = [tag.strip() for tag in tags_raw if isinstance(tag, str) and tag.strip()] if isinstance(tags_raw, list) else []
            if content is None or why is None or not evidence:
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
        for raw in items[:MAX_LIST_LINES]:
            if not isinstance(raw, dict):
                continue
            path_or_file_id = optional_text(raw.get("path_or_file_id"))
            reason = optional_text(raw.get("reason"))
            evidence = normalize_evidence(raw.get("evidence_event_ids"), valid_event_ids)
            if path_or_file_id is None or reason is None or not evidence:
                continue
            output.append({"path_or_file_id": path_or_file_id, "reason": reason, "evidence_event_ids": evidence})
        return output
