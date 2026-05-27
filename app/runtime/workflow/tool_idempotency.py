"""Business idempotency keys for workflow tools."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.domain.models import RunContext, ToolCall

__all__ = ["tool_idempotency_key"]

_NOTE_SOURCE_TYPE_ALIASES = {
    "application": "career_application",
    "career_application": "career_application",
    "resume_profile": "resume_profile",
    "career_resume_profile": "resume_profile",
    "career_profile": "career_profile",
    "jd": "jd_analysis",
    "jd_analysis": "jd_analysis",
    "career_jd_analysis": "jd_analysis",
    "fit": "job_fit_report",
    "job_fit": "job_fit_report",
    "job_fit_report": "job_fit_report",
    "career_job_fit_report": "job_fit_report",
    "resume_version": "resume_version",
    "career_resume_version": "resume_version",
    "artifact": "artifact",
    "chat_message": "chat_message",
    "message": "chat_message",
    "manual": "manual",
}
_NOTE_TYPED_REF_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_-]*)\s*[:=]\s*([A-Za-z0-9][A-Za-z0-9_-]*)\s*$")


def tool_idempotency_key(
    tool_call: ToolCall,
    context: RunContext,
    *,
    pending_runtime_plan: dict[str, Any] | None = None,
) -> str | None:
    """Return a conservative business idempotency key for high-value workflow tools."""

    args = tool_call.arguments
    if tool_call.name == "delegate_agents":
        signature = _delegate_semantic_signature(args)
        return f"delegate_agents:{context.session_id}:{context.run_id}:{signature}" if signature is not None else None
    if tool_call.name == "career_resume_profile_save":
        return _key_from_fields("career_resume_profile_save", context.session_id, args, ("source_artifact_id",))
    if tool_call.name == "career_jd_analysis_save":
        return _key_from_fields("career_jd_analysis_save", context.session_id, args, ("source_artifact_id",))
    if tool_call.name == "session_create_text_artifact":
        output_kind = _workflow_output_kind_from_runtime_plan(pending_runtime_plan) or _workflow_output_kind(args)
        if output_kind is None:
            return None
        source_scope = _workflow_output_source_scope(output_kind, pending_runtime_plan)
        task_or_run = _string_or_none(context.parent_run_id) or context.run_id
        scope = f"{task_or_run}:{source_scope}" if source_scope is not None else task_or_run
        return f"session_create_text_artifact:{context.session_id}:{scope}:{output_kind}"
    if tool_call.name == "career_job_fit_report_save":
        key = _key_from_fields(
            "career_job_fit_report_save",
            context.session_id,
            args,
            ("jd_analysis_id", "resume_profile_id"),
        )
        if key is not None:
            return key
        return _key_from_fields("career_job_fit_report_save", context.session_id, args, ("report_artifact_id",))
    if tool_call.name == "career_application_create":
        return _key_from_fields(
            "career_application_create",
            context.session_id,
            args,
            ("jd_analysis_id", "resume_profile_id", "job_fit_report_id"),
        )
    if tool_call.name == "career_resume_version_create":
        # Run-scoped on purpose: a later user turn may explicitly ask for a new version.
        return _key_from_fields(
            "career_resume_version_create",
            f"{context.session_id}:{context.run_id}",
            args,
            ("base_resume_profile_id", "target_jd_analysis_id"),
            aliases={"base_resume_profile_id": ("resume_profile_id",)},
        )
    if tool_call.name == "career_application_merge":
        application_id = _string_or_none(args.get("application_id"))
        if application_id is None:
            return None
        updates = args.get("updates")
        if isinstance(updates, dict):
            version_ids = [
                item.strip()
                for item in updates.get("resume_version_ids", [])
                if isinstance(item, str) and item.strip()
            ]
            if version_ids:
                return (
                    f"career_application_merge:{context.session_id}:{application_id}:"
                    f"resume_version_ids:{','.join(sorted(dict.fromkeys(version_ids)))}"
                )
        stable_update_hash = _stable_hash(updates if isinstance(updates, dict) else {})
        return f"career_application_merge:{context.session_id}:{application_id}:updates:{stable_update_hash}"
    if tool_call.name == "note_create":
        note_id = _string_or_none(args.get("note_id"))
        if note_id is not None:
            return f"note_create:{context.session_id}:{note_id}"
        stable_note_hash = _stable_hash(
            {
                "title": _string_or_none(args.get("title")),
                "body_markdown": _string_or_none(args.get("body_markdown")),
                "related_application_id": _string_or_none(args.get("related_application_id")),
                "evidence_refs": _note_reference_list(args),
            }
        )
        return f"note_create:{context.session_id}:{context.run_id}:{stable_note_hash}"
    if tool_call.name == "note_append":
        note_id = _string_or_none(args.get("note_id"))
        if note_id is None:
            return None
        stable_append_hash = _stable_hash({"body_markdown": _string_or_none(args.get("body_markdown"))})
        return f"note_append:{context.session_id}:{note_id}:{stable_append_hash}"
    if tool_call.name == "learning_task_create":
        task_id = _string_or_none(args.get("learning_task_id"))
        if task_id is not None:
            return f"learning_task_create:{context.session_id}:{task_id}"
        stable_task_hash = _stable_hash(
            {
                "title": _string_or_none(args.get("title")),
                "learning_plan_id": _string_or_none(args.get("learning_plan_id")),
                "evidence_refs": _string_list(args.get("evidence_refs")),
            }
        )
        return f"learning_task_create:{context.session_id}:{context.run_id}:{stable_task_hash}"
    return None


def _key_from_fields(
    tool_name: str,
    scope: str,
    args: dict[str, Any],
    fields: tuple[str, ...],
    *,
    aliases: dict[str, tuple[str, ...]] | None = None,
) -> str | None:
    values: list[str] = []
    for field in fields:
        value = _string_or_none(args.get(field))
        for alias in (aliases or {}).get(field, ()):
            value = value or _string_or_none(args.get(alias))
        if value is None:
            return None
        values.append(f"{field}={value}")
    return f"{tool_name}:{scope}:{'|'.join(values)}"


def _delegate_semantic_signature(args: dict[str, Any]) -> str | None:
    raw_tasks = args.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        return None
    normalized_tasks: list[dict[str, Any]] = []
    for raw_task in raw_tasks:
        if not isinstance(raw_task, dict):
            continue
        target = _string_or_none(raw_task.get("target_agent_id"))
        instruction = _string_or_none(raw_task.get("instruction"))
        if target is None or instruction is None:
            continue
        refs = sorted(
            ref.strip()
            for ref in raw_task.get("artifact_refs", [])
            if isinstance(ref, str) and ref.strip()
        )
        normalized_tasks.append(
            {
                "target_agent_id": target,
                "artifact_refs": refs,
                "instruction_digest": _stable_text_digest(_semantic_instruction_text(instruction)),
            }
        )
    if not normalized_tasks:
        return None
    return _stable_hash(sorted(normalized_tasks, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)))


def _workflow_output_kind_from_runtime_plan(plan: dict[str, Any] | None) -> str | None:
    if not isinstance(plan, dict):
        return None
    phase = _string_or_none(plan.get("phase"))
    missing_outputs = {
        item.strip()
        for item in plan.get("missing_outputs", [])
        if isinstance(item, str) and item.strip()
    }
    required_tools = {
        item.strip()
        for item in (plan.get("required_tools") or plan.get("next_allowed_tools") or [])
        if isinstance(item, str) and item.strip()
    }
    if "session_create_text_artifact" not in required_tools:
        return None
    if phase == "resume_diagnosis" and "diagnosis_artifact" in missing_outputs:
        return "resume_diagnosis"
    if phase == "jd_fit":
        if "jd_source_artifact" in missing_outputs:
            return "jd_source"
        if "job_fit_report_artifact" in missing_outputs or "job_fit_report" in missing_outputs:
            return "job_fit_report"
    if phase == "resume_version" and "resume_version" in missing_outputs:
        return "resume_version_artifact"
    return None


def _workflow_output_source_scope(output_kind: str, plan: dict[str, Any] | None) -> str | None:
    if not isinstance(plan, dict):
        return None
    refs = plan.get("known_refs") or plan.get("completed_refs") or {}
    if not isinstance(refs, dict):
        return None
    if output_kind == "job_fit_report":
        source = (
            _string_or_none(refs.get("jd_source_artifact_id"))
            or _string_or_none(refs.get("source_artifact_id"))
            or _string_or_none(refs.get("jd_analysis_id"))
        )
        return f"jd={source}" if source is not None else None
    if output_kind == "resume_diagnosis":
        source = (
            _string_or_none(refs.get("resume_source_artifact_id"))
            or _string_or_none(refs.get("source_artifact_id"))
            or _string_or_none(refs.get("resume_profile_id"))
        )
        return f"resume={source}" if source is not None else None
    if output_kind == "resume_version_artifact":
        source = (
            _string_or_none(refs.get("jd_analysis_id"))
            or _string_or_none(refs.get("target_jd_analysis_id"))
            or _string_or_none(refs.get("job_fit_report_id"))
        )
        return f"target={source}" if source is not None else None
    return None


def _workflow_output_kind(args: dict[str, Any]) -> str | None:
    kind = _string_or_none(args.get("kind")) or "generated_file"
    if kind != "generated_file":
        return None
    title_kind = _workflow_output_kind_from_text(_string_or_none(args.get("title")) or "")
    if title_kind is not None:
        return title_kind
    content_kind = _workflow_output_kind_from_text(_string_or_none(args.get("content")) or "")
    if content_kind is not None:
        return content_kind
    return None


def _workflow_output_kind_from_text(text: str) -> str | None:
    normalized = text.casefold()
    compact = "".join(ch for ch in normalized if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")
    if "resume_diagnosis" in normalized or ("resume" in compact and "diagnosis" in compact):
        return "resume_diagnosis"
    if "简历" in compact and ("诊断" in compact or "画像" in compact) and "报告" in compact:
        return "resume_diagnosis"
    if "岗位匹配" in compact or "匹配报告" in compact or ("jobfit" in compact and "report" in compact):
        return "job_fit_report"
    if ("resumeversion" in compact) or ("简历版本" in compact or "定制简历" in compact):
        return "resume_version_artifact"
    return None


def _semantic_instruction_text(text: str) -> str:
    normalized = text.casefold()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"workflowruntime[^。.\n]*(?:[。.]|$)", "", normalized)
    return normalized.strip()


def _stable_text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _note_reference_list(args: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    refs.extend(_note_evidence_refs(args.get("evidence_refs")))
    refs.extend(_note_source_ref_ids(args.get("source_refs")))
    return sorted(dict.fromkeys(refs))


def _note_evidence_refs(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [_normalize_note_ref(value)]
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            refs.append(_normalize_note_ref(item))
            continue
        if isinstance(item, dict):
            ref = _note_ref_from_object(item)
            if ref is not None:
                refs.append(_normalize_note_ref(ref))
    return refs


def _note_source_ref_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_id = _string_or_none(item.get("source_id"))
        if source_id is not None:
            refs.append(_normalize_note_ref(source_id))
    return refs


def _note_ref_from_object(item: dict[str, Any]) -> str | None:
    for key in (
        "source_id",
        "record_id",
        "id",
        "artifact_id",
        "application_id",
        "resume_profile_id",
        "career_profile_id",
        "jd_analysis_id",
        "job_fit_report_id",
        "resume_version_id",
        "note_id",
        "learning_task_id",
    ):
        value = _string_or_none(item.get(key))
        if value is not None:
            return value
    return None


def _normalize_note_ref(raw: str) -> str:
    value = raw.strip().strip("`")
    match = _NOTE_TYPED_REF_RE.fullmatch(value)
    if match is None:
        return value
    source_type = _NOTE_SOURCE_TYPE_ALIASES.get(match.group(1).strip().lower())
    if source_type is None:
        return value
    return match.group(2).strip()
