"""Model-visible compact views for tool results."""

from __future__ import annotations

import json
import re
from typing import Any

__all__ = ["compact_tool_result_for_model"]

_SMALL_RESULT_LIMIT = 1600
_DEFAULT_COMPACT_LIMIT = 5000
_FULL_RESULT_HINT = "完整工具结果已写入事件日志；如需更多细节，请基于保留的 id / artifact_id 继续读取。"
_TOOL_SEARCH_NAME = "tool_search"
_RETRIEVAL_TOOLS = {"retrieval_search", "retrieval_context_pack"}
_DELEGATION_TOOLS = {"delegate_agents", "agent_task_status"}


def compact_tool_result_for_model(
    *,
    tool_name: str,
    success: bool,
    content: str,
    max_chars: int = _DEFAULT_COMPACT_LIMIT,
) -> str:
    """Return the tool-result content that should be replayed to the model.

    Full tool results remain in the event log. This function only controls the
    next model call's `tool` message, where large retrieval/delegation/product
    payloads otherwise get replayed on every tool round.
    """

    if tool_name == _TOOL_SEARCH_NAME and success:
        payload = _loads_json(content)
        if payload is not None:
            return _dump_bounded(_compact_tool_search_payload(payload), max_chars=1800)
    if len(content) <= _SMALL_RESULT_LIMIT:
        return content
    if not success:
        return _compact_plain_result(tool_name=tool_name, content=content, max_chars=max_chars)

    payload = _loads_json(content)
    if payload is None:
        return content

    if tool_name in _RETRIEVAL_TOOLS:
        compact = _compact_retrieval_payload(tool_name=tool_name, payload=payload)
    elif tool_name in _DELEGATION_TOOLS:
        compact = _compact_delegation_payload(tool_name=tool_name, payload=payload)
    elif _is_product_tool(tool_name):
        compact = _compact_product_payload(tool_name=tool_name, payload=payload)
    else:
        return content

    return _dump_bounded(compact, max_chars=max_chars)


def _loads_json(content: str) -> Any | None:
    try:
        return json.loads(content)
    except (TypeError, ValueError):
        return None


def _compact_tool_search_payload(payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    revealed_tool_names = _compact_string_list(data.get("revealed_tool_names"), limit=40, item_chars=80)
    return _drop_none(
        {
            "tool": _TOOL_SEARCH_NAME,
            "model_view": "compact",
            "query": _text(data.get("query"), 180),
            "matched_groups": _compact_string_list(data.get("matched_groups"), limit=8, item_chars=40),
            "reveal_packs": _compact_string_list(data.get("reveal_packs"), limit=8, item_chars=40),
            "revealed_tool_count": data.get("revealed_tool_count"),
            "revealed_tool_names": revealed_tool_names,
            "available_tool_count": data.get("available_tool_count"),
            "next_step": _text(data.get("next_step"), 240),
            "search_guidance": _text(data.get("search_guidance"), 240),
        }
    )


def _compact_retrieval_payload(*, tool_name: str, payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    context_pack = data.get("context_pack") if isinstance(data.get("context_pack"), dict) else data
    query = data.get("query")
    if not query and isinstance(context_pack, dict):
        query = context_pack.get("query")
    hits = _as_list(context_pack.get("hits") if isinstance(context_pack, dict) else None)
    citations = _as_list(context_pack.get("citations") if isinstance(context_pack, dict) else None)
    compact_hits = [_compact_retrieval_hit(hit) for hit in hits[:6]]
    context_pack_hits = [_minimal_retrieval_hit(hit) for hit in hits[:20]]
    compact_context_pack = _drop_none(
        {
            "query": _text(query, 180),
            "context_char_count": data.get("context_char_count")
            or (context_pack.get("context_char_count") if isinstance(context_pack, dict) else None),
            "hits": context_pack_hits,
            "grouped_context": _compact_grouped_context(context_pack),
            "citations": [_compact_source_ref(citation) for citation in citations[:8]],
            "omitted_count": data.get("omitted_count")
            or (context_pack.get("omitted_count") if isinstance(context_pack, dict) else None),
        }
    )
    return _drop_none(
        {
            "tool": tool_name,
            "model_view": "compact",
            "query": _text(query, 180),
            "session_id": data.get("session_id"),
            "count": data.get("count") if isinstance(data.get("count"), int) else len(hits),
            "context_char_count": data.get("context_char_count")
            or (context_pack.get("context_char_count") if isinstance(context_pack, dict) else None),
            "max_chars": data.get("max_chars"),
            "omitted_count": data.get("omitted_count")
            or (context_pack.get("omitted_count") if isinstance(context_pack, dict) else None),
            "group_counts": data.get("group_counts") or _derive_group_counts(context_pack),
            "top_hits": compact_hits,
            "citations": [_compact_source_ref(citation) for citation in citations[:8]],
            "context_pack": compact_context_pack,
            "full_result_hint": _FULL_RESULT_HINT,
        }
    )


def _compact_retrieval_hit(hit: Any) -> dict[str, Any]:
    data = hit if isinstance(hit, dict) else {}
    return _drop_none(
        {
            "source": _compact_source_ref(data.get("source")),
            "title": _text(data.get("title"), 140),
            "summary": _text(data.get("summary"), 240),
            "snippet": _text(data.get("snippet"), 360),
            "tags": _compact_string_list(data.get("tags"), limit=8, item_chars=40),
            "score": data.get("score"),
            "match_reason": _text(data.get("match_reason"), 180),
            "evidence_refs": _compact_string_list(data.get("evidence_refs"), limit=8, item_chars=120),
            "updated_at": data.get("updated_at"),
        }
    )


def _compact_source_ref(source: Any) -> dict[str, Any] | None:
    if not isinstance(source, dict):
        return None
    return _drop_none(
        {
            "source_type": source.get("source_type"),
            "source_id": source.get("source_id"),
            "source_session_id": source.get("source_session_id"),
            "artifact_id": source.get("artifact_id"),
        }
    )


def _derive_group_counts(context_pack: Any) -> dict[str, int]:
    if not isinstance(context_pack, dict):
        return {}
    grouped = context_pack.get("grouped_context")
    if not isinstance(grouped, dict):
        return {}
    return {str(group): len(items) for group, items in grouped.items() if isinstance(items, list)}


def _compact_grouped_context(context_pack: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(context_pack, dict):
        return {}
    grouped = context_pack.get("grouped_context")
    if not isinstance(grouped, dict):
        return {}
    output: dict[str, list[dict[str, Any]]] = {}
    for group, items in grouped.items():
        if not isinstance(items, list):
            continue
        compact_items = [_compact_grouped_hit(item) for item in items[:4]]
        if compact_items:
            output[str(group)] = compact_items
    return output


def _compact_grouped_hit(hit: Any) -> dict[str, Any]:
    data = hit if isinstance(hit, dict) else {}
    return _drop_none(
        {
            "source": _compact_source_ref(data.get("source")),
            "title": _text(data.get("title"), 140),
            "score": data.get("score"),
            "match_reason": _text(data.get("match_reason"), 160),
            "updated_at": data.get("updated_at"),
        }
    )


def _compact_delegation_payload(*, tool_name: str, payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    results = _as_list(data.get("results") or data.get("tasks"))
    return _drop_none(
        {
            "tool": tool_name,
            "model_view": "compact",
            "task_group_id": data.get("task_group_id"),
            "status": data.get("status"),
            "max_concurrency": data.get("max_concurrency"),
            "message": _text(data.get("message"), 240),
            "results": [_compact_delegate_result(item) for item in results[:8]],
            "full_result_hint": _FULL_RESULT_HINT,
        }
    )


def _compact_delegate_result(item: Any) -> dict[str, Any]:
    data = item if isinstance(item, dict) else {}
    return _drop_none(
        {
            "task_id": data.get("task_id"),
            "target_agent_id": data.get("target_agent_id"),
            "status": data.get("status"),
            "summary": _text(data.get("summary"), 500),
            "answer_preview": _text(data.get("answer"), 700),
            "extracted_ids": _extract_known_ids(data),
            "followup_hints": _delegate_followup_hints(data),
            "child_run_id": data.get("child_run_id"),
            "artifact_refs": _compact_string_list(data.get("artifact_refs"), limit=12, item_chars=120),
            "next_steps": _compact_string_list(data.get("next_steps"), limit=6, item_chars=160),
            "error": _text(data.get("error"), 300),
        }
    )


def _delegate_followup_hints(data: dict[str, Any]) -> list[str] | None:
    if data.get("status") != "completed":
        return None
    target_agent_id = data.get("target_agent_id")
    if target_agent_id == "resume_agent":
        return [
            "If the result includes a resume_profile_id, update career_profile_default with career_profile_merge before finalizing the resume diagnosis turn.",
            "If career tools are not visible yet, call tool_search for the career group first.",
        ]
    if target_agent_id == "job_agent":
        return [
            "Use returned jd_analysis_id, job_fit_report_id, report_artifact_id, resume_profile_id, and career_profile_id directly.",
            "Do not call status/list/get tools only to reconfirm completed child results.",
        ]
    return None


def _compact_product_payload(*, tool_name: str, payload: Any) -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    record_type = _text(data.get("record_type"), 80)
    records = data.get("records")
    if isinstance(records, list):
        return _drop_none(
            {
                "tool": tool_name,
                "model_view": "compact",
                "record_type": record_type,
                "count": len(records),
                "records": [_compact_product_record(item, record_type=record_type) for item in records[:8]],
                "full_result_hint": _FULL_RESULT_HINT,
            }
        )

    record = data.get("record")
    compact: dict[str, Any] = {
        "tool": tool_name,
        "model_view": "compact",
        "ids": _collect_id_fields(data),
        "status": data.get("status"),
        "found": data.get("found"),
        "record_type": record_type,
        "title": _text(data.get("title") or data.get("name") or data.get("position"), 160),
        "summary": _text(data.get("summary") or data.get("description"), 500),
        "score": data.get("overall_score") or data.get("score") or data.get("fit_score"),
        "recommendation": _text(data.get("recommendation"), 220),
        "evidence_refs": _compact_string_list(data.get("evidence_refs"), limit=10, item_chars=140),
        "source_refs": _compact_string_list(data.get("source_refs"), limit=10, item_chars=140),
        "next_actions": _compact_string_list(data.get("next_actions"), limit=6, item_chars=160),
        "risks": _compact_string_list(data.get("risks"), limit=6, item_chars=180),
        "record": _compact_product_record(record, record_type=record_type),
        "items_preview": _compact_nested_items(data),
        "completion_hint": _product_completion_hint(tool_name=tool_name),
        "full_result_hint": _FULL_RESULT_HINT,
    }
    return _drop_none(compact)


def _product_completion_hint(*, tool_name: str) -> str | None:
    if tool_name == "career_resume_version_create":
        return "ResumeVersion 已保存；除非工具失败或用户明确要求另一版，否则不要再次创建 ResumeVersion。"
    if tool_name == "career_application_merge":
        return "CareerApplication 已更新；如果本轮目标已完成，直接给最终答复，不要重新读取全部关联记录。"
    if tool_name in {"career_jd_analysis_save", "career_job_fit_report_save"}:
        return "记录已保存；不要重复保存同一份分析结果。"
    return None


def _compact_product_record(record: Any, *, record_type: str | None) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    keys = _product_record_keys(record_type=record_type)
    output: dict[str, Any] = {}
    for key in keys:
        if key in record:
            output[key] = _compact_value(record[key], text_chars=260)
    return _drop_none(output)


def _product_record_keys(*, record_type: str | None) -> list[str]:
    common = [
        "status",
        "source_artifact_id",
        "artifact_id",
        "report_artifact_id",
        "raw_text_artifact_id",
        "diagnosis_artifact_id",
        "evidence_refs",
        "updated_at",
    ]
    id_keys = [
        "resume_profile_id",
        "career_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
        "resume_version_id",
        "application_id",
        "base_resume_profile_id",
        "target_jd_analysis_id",
        "resume_version_ids",
    ]
    type_keys: dict[str, list[str]] = {
        "resume_profile": [
            "basic_info",
            "education",
            "work_experience",
            "project_experience",
            "skills",
            "self_evaluation",
            "diagnosis",
        ],
        "career_profile": [
            "career_goal",
            "target_roles",
            "preferred_industries",
            "preferred_cities",
            "strengths",
            "weaknesses",
            "skills",
            "resume_issues",
            "interview_weaknesses",
        ],
        "jd_analysis": [
            "company",
            "position",
            "seniority",
            "required_skills",
            "preferred_skills",
            "responsibilities",
            "keywords",
            "risk_signals",
            "interview_focus",
        ],
        "job_fit_report": [
            "overall_score",
            "score_breakdown",
            "recommendation",
            "matched_evidence",
            "gaps",
            "resume_optimization_direction",
            "interview_preparation_focus",
        ],
        "resume_version": [
            "title",
            "format",
            "change_summary",
            "keyword_strategy",
            "risk_notes",
        ],
        "career_application": [
            "company",
            "position",
            "location",
            "stage",
            "priority",
            "summary",
            "next_actions",
            "risks",
            "notes",
        ],
    }
    specific = type_keys.get(record_type or "", [])
    return _dedupe_keys(id_keys + common + specific)


def _collect_id_fields(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            continue
        if key.endswith("_id") or key.endswith("_ids") or key in {"id", "artifact_id", "artifact_refs"}:
            output[key] = _compact_value(value, text_chars=160)
    return output


def _compact_nested_items(payload: dict[str, Any]) -> dict[str, list[Any]]:
    output: dict[str, list[Any]] = {}
    for key, value in payload.items():
        if not isinstance(value, list) or key in {"evidence_refs", "source_refs", "artifact_refs"}:
            continue
        compact_items = [_compact_value(item, text_chars=180) for item in value[:4]]
        if compact_items:
            output[key] = compact_items
    return output


def _compact_value(value: Any, *, text_chars: int) -> Any:
    if isinstance(value, str):
        return _text(value, text_chars)
    if isinstance(value, int | float | bool) or value is None:
        return value
    if isinstance(value, list):
        return [_compact_value(item, text_chars=text_chars) for item in value[:8]]
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in list(value.items())[:8]:
            if isinstance(key, str):
                output[key] = _compact_value(item, text_chars=text_chars)
        return output
    return _text(str(value), text_chars)


def _is_product_tool(tool_name: str) -> bool:
    return tool_name.startswith(("career_", "note_", "learning_"))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _compact_string_list(value: Any, *, limit: int, item_chars: int) -> list[str] | None:
    if not isinstance(value, list):
        return None
    output: list[str] = []
    for item in value[:limit]:
        if not isinstance(item, str) or not item.strip():
            continue
        compact = _text(item, item_chars)
        if compact:
            output.append(compact)
    return output or None


def _text(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return _truncate(text, limit)


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != {} and value != []}


def _dedupe_keys(keys: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for key in keys:
        if key in seen:
            continue
        output.append(key)
        seen.add(key)
    return output


def _dump_bounded(payload: dict[str, Any], *, max_chars: int) -> str:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(content) <= max_chars:
        return content
    reduced = dict(payload)
    if isinstance(reduced.get("context_pack"), dict):
        reduced["context_pack"] = _minimal_context_pack(reduced["context_pack"])
        reduced.pop("top_hits", None)
    if isinstance(reduced.get("top_hits"), list):
        reduced["top_hits"] = reduced["top_hits"][:3]
    if isinstance(reduced.get("results"), list):
        reduced["results"] = reduced["results"][:4]
    if isinstance(reduced.get("items_preview"), dict):
        reduced["items_preview"] = {}
    reduced["truncated"] = True
    content = json.dumps(_shorten_strings(reduced, 180), ensure_ascii=False, separators=(",", ":"))
    if len(content) <= max_chars:
        return content
    fallback = {
        "tool": payload.get("tool", "unknown"),
        "model_view": "compact",
        "truncated": True,
        "full_result_hint": _FULL_RESULT_HINT,
    }
    if isinstance(payload.get("context_pack"), dict):
        fallback["context_pack"] = _minimal_context_pack(payload["context_pack"])
    else:
        fallback["content_preview"] = _truncate(content, max(200, max_chars - 320))
    return json.dumps(fallback, ensure_ascii=False, separators=(",", ":"))


def _minimal_context_pack(context_pack: Any) -> dict[str, Any]:
    if not isinstance(context_pack, dict):
        return {}
    hits = _as_list(context_pack.get("hits"))
    citations = _as_list(context_pack.get("citations"))
    grouped = context_pack.get("grouped_context")
    output: dict[str, Any] = {
        "query": _text(context_pack.get("query"), 160),
        "context_char_count": context_pack.get("context_char_count"),
        "hits": [_minimal_retrieval_hit(hit) for hit in hits[:12]],
        "citations": [_compact_source_ref(citation) for citation in citations[:8]],
        "omitted_count": context_pack.get("omitted_count"),
    }
    if isinstance(grouped, dict):
        grouped_output: dict[str, list[dict[str, Any]]] = {}
        for group, items in grouped.items():
            if not isinstance(items, list):
                continue
            compact_items = [_minimal_retrieval_hit(item) for item in items[:3]]
            if compact_items:
                grouped_output[str(group)] = compact_items
        output["grouped_context"] = grouped_output
    return _drop_none(output)


def _minimal_retrieval_hit(hit: Any) -> dict[str, Any]:
    data = hit if isinstance(hit, dict) else {}
    return _drop_none(
        {
            "source": _compact_source_ref(data.get("source")),
            "title": _text(data.get("title"), 120),
            "score": data.get("score"),
            "match_reason": _text(data.get("match_reason"), 120),
            "updated_at": data.get("updated_at"),
        }
    )


def _shorten_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(value, limit)
    if isinstance(value, list):
        return [_shorten_strings(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: _shorten_strings(item, limit) for key, item in value.items()}
    return value


def _compact_plain_result(*, tool_name: str, content: str, max_chars: int) -> str:
    payload = {
        "tool": tool_name,
        "model_view": "compact",
        "content_preview": _truncate(content, max(200, max_chars - 260)),
        "full_result_hint": _FULL_RESULT_HINT,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


_KNOWN_ID_PATTERN = re.compile(
    r"\b(?:artifact|resume_profile|career_profile|resume_version|application|fit|jd|note|learning_task|learning_plan|weakness)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}\b"
)
_KNOWN_ID_FIELD_NAMES = {
    "artifact_id",
    "resume_profile_id",
    "career_profile_id",
    "resume_version_id",
    "application_id",
    "jd_analysis_id",
    "job_fit_report_id",
    "learning_task_id",
    "learning_plan_id",
    "note_id",
    "weakness_id",
}


def _extract_known_ids(value: Any) -> list[str] | None:
    text = _collect_text(value)
    if not text:
        return None
    output: list[str] = []
    seen: set[str] = set()
    for match in _KNOWN_ID_PATTERN.finditer(text):
        item = match.group(0)
        if item in _KNOWN_ID_FIELD_NAMES or item in seen:
            continue
        output.append(item)
        seen.add(item)
        if len(output) >= 24:
            break
    return output or None


def _collect_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, int | float | bool):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_collect_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_collect_text(item) for item in value.values())
    return str(value)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return f"{text[: limit - 1]}…"
