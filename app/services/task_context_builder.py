"""Build deterministic input snapshots for delegated child-agent tasks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from app.career.store import CareerProductStore
from app.domain.models import RunContext
from app.domain.protocols import SessionRepository
from app.domain.reference_ids import is_reserved_reference_value
from app.runtime.context.workflow_state import extract_current_workflow_state

__all__ = ["TaskContextBuilder"]

_ARTIFACT_PREVIEW_CHARS = 2400
_RECORD_STRING_CHARS = 700
_LIST_ITEMS = 12
_DICT_ITEMS = 24
_ID_PATTERN = re.compile(
    r"\b(?:artifact|resume_profile|career_profile|resume_version|application|fit|jd)_[A-Za-z0-9][A-Za-z0-9_-]{0,127}\b"
)


class TaskContextBuilder:
    """Prepare code-owned task context before invoking a child agent."""

    def __init__(
        self,
        *,
        session_repository: SessionRepository,
        career_store: CareerProductStore,
    ) -> None:
        self._session_repository = session_repository
        self._career_store = career_store

    def build(
        self,
        *,
        source_context: RunContext,
        target_agent_id: str,
        task_id: str,
        instruction: str,
        artifact_refs: list[str],
    ) -> dict[str, Any]:
        events = self._session_repository.list_events(source_context.session_id)
        workflow_state = extract_current_workflow_state(events, source_context)
        provided_artifacts = [
            snapshot
            for artifact_id in artifact_refs
            if (snapshot := self._artifact_snapshot(source_context.session_id, artifact_id)) is not None
        ]
        known_refs: dict[str, str] = dict(workflow_state.refs)
        _merge_refs_from_text(known_refs, instruction)
        _merge_artifact_refs(
            known_refs,
            target_agent_id=target_agent_id,
            artifact_refs=artifact_refs,
            provided_artifacts=provided_artifacts,
        )
        provided_records = self._provided_records(known_refs, target_agent_id=target_agent_id)
        missing_inputs = _missing_inputs(
            target_agent_id=target_agent_id,
            known_refs=known_refs,
            provided_records=provided_records,
            provided_artifacts=provided_artifacts,
        )
        reuse_policy = _reuse_policy(provided_artifacts=provided_artifacts, provided_records=provided_records)

        return _drop_empty(
            {
                "schema_version": 1,
                "task_id": task_id,
                "target_agent_id": target_agent_id,
                "phase": _phase_for_agent(target_agent_id),
                "known_refs": known_refs,
                "provided_artifacts": provided_artifacts,
                "provided_records": provided_records,
                "missing_inputs": missing_inputs,
                "provided_inputs_complete": not missing_inputs,
                "required_outputs": _required_outputs_for_agent(target_agent_id),
                "allowed_initial_tools": _allowed_initial_tools_for_agent(target_agent_id),
                "reuse_policy": reuse_policy,
            }
        )

    def _artifact_snapshot(self, session_id: str, artifact_id: str) -> dict[str, Any] | None:
        artifact = self._session_repository.get_session_artifact(session_id, artifact_id)
        if artifact is None:
            return None
        text = ""
        read_error: str | None = None
        try:
            text = self._session_repository.read_session_artifact_text(session_id, artifact_id)
        except Exception as exc:  # noqa: BLE001
            read_error = str(exc).strip() or exc.__class__.__name__
        preview = _truncate_text(text, _ARTIFACT_PREVIEW_CHARS)
        return _drop_empty(
            {
                "artifact_id": artifact.artifact_id,
                "title": artifact.title,
                "kind": artifact.kind,
                "media_type": artifact.media_type,
                "status": artifact.status,
                "visibility": artifact.visibility,
                "owner_agent_id": artifact.owner_agent_id,
                "description": artifact.description,
                "source_type": artifact.source_type,
                "text_char_count": artifact.text_char_count if artifact.text_char_count is not None else len(text),
                "token_estimate": artifact.token_estimate,
                "updated_at": _iso(artifact.updated_at),
                "content_hash": _hash_text(text) if text else None,
                "text_preview": preview,
                "text_truncated": bool(text and len(preview) < len(text.strip())),
                "read_error": read_error,
            }
        )

    def _provided_records(self, known_refs: dict[str, str], *, target_agent_id: str) -> dict[str, Any]:
        records: dict[str, Any] = {}
        _put_record(
            records,
            "resume_profile",
            known_refs.get("resume_profile_id"),
            self._career_store.get_resume_profile,
        )
        career_profile_id = known_refs.get("career_profile_id")
        if career_profile_id is None and target_agent_id == "job_agent":
            default_profile = self._safe_get(lambda: self._career_store.get_career_profile("career_profile_default"))
            if default_profile is not None:
                known_refs["career_profile_id"] = "career_profile_default"
                records["career_profile"] = _record_snapshot("career_profile", "career_profile_default", default_profile)
        else:
            _put_record(
                records,
                "career_profile",
                career_profile_id,
                self._career_store.get_career_profile,
            )
        _put_record(
            records,
            "jd_analysis",
            known_refs.get("jd_analysis_id"),
            self._career_store.get_jd_analysis,
        )
        _put_record(
            records,
            "job_fit_report",
            known_refs.get("job_fit_report_id"),
            self._career_store.get_job_fit_report,
        )
        _put_record(
            records,
            "career_application",
            known_refs.get("application_id"),
            self._career_store.get_career_application,
        )
        return records

    def _safe_get(self, getter: Any) -> Any | None:
        try:
            return getter()
        except Exception:  # noqa: BLE001
            return None


def _put_record(records: dict[str, Any], record_type: str, record_id: str | None, getter: Any) -> None:
    if record_id is None:
        return
    try:
        record = getter(record_id)
    except Exception:  # noqa: BLE001
        return
    if record is None:
        return
    records[record_type] = _record_snapshot(record_type, record_id, record)


def _record_snapshot(record_type: str, record_id: str, record: Any) -> dict[str, Any]:
    snapshot = _bounded_value(record)
    return _drop_empty(
        {
            "record_type": record_type,
            "record_id": record_id,
            "updated_at": _field_iso(record, "updated_at"),
            "content_hash": _hash_json(snapshot),
            "snapshot": snapshot,
        }
    )


def _merge_artifact_refs(
    known_refs: dict[str, str],
    *,
    target_agent_id: str,
    artifact_refs: list[str],
    provided_artifacts: list[dict[str, Any]],
) -> None:
    valid_refs = [artifact_id for artifact_id in artifact_refs if artifact_id.startswith("artifact_")]
    if not valid_refs:
        return
    roles = {
        str(item.get("artifact_id")): _artifact_role(item)
        for item in provided_artifacts
        if isinstance(item.get("artifact_id"), str)
    }
    if target_agent_id == "resume_agent":
        resume_ref = _first_ref_for_role(valid_refs, roles, "resume") or valid_refs[0]
        known_refs.setdefault("resume_source_artifact_id", resume_ref)
        return
    if target_agent_id == "job_agent":
        jd_ref = _first_ref_for_role(valid_refs, roles, "jd") or valid_refs[0]
        known_refs.setdefault("jd_source_artifact_id", jd_ref)
        known_refs.setdefault("source_artifact_id", jd_ref)
        job_resume_ref = _first_ref_for_role(valid_refs, roles, "resume")
        if job_resume_ref is not None:
            known_refs.setdefault("resume_source_artifact_id", job_resume_ref)
        return
    for artifact_id in valid_refs:
        if not artifact_id.startswith("artifact_"):
            continue
        known_refs.setdefault("source_artifact_id", artifact_id)


def _first_ref_for_role(refs: list[str], roles: dict[str, str | None], role: str) -> str | None:
    for artifact_id in refs:
        if roles.get(artifact_id) == role:
            return artifact_id
    return None


def _artifact_role(snapshot: dict[str, Any]) -> str | None:
    text = " ".join(
        str(snapshot.get(key) or "")
        for key in ("artifact_id", "title", "description", "text_preview")
    ).casefold()
    compact = _normalize_text_key(text)
    if _has_any(
        compact,
        (
            "jobdescription",
            "岗位jd",
            "目标岗位",
            "招聘",
            "职位描述",
            "任职要求",
            "岗位要求",
        ),
    ) or re.search(r"\bjd\b", text):
        return "jd"
    if _has_any(compact, ("resume", "cv", "candidate", "候选人", "简历", "工作经历", "项目经历")):
        return "resume"
    return None


def _normalize_text_key(text: str) -> str:
    return re.sub(r"[\s_\-—:：|｜/\\（）()【】\[\].。]+", "", text.strip().casefold())


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _merge_refs_from_text(known_refs: dict[str, str], text: str) -> None:
    for match in _ID_PATTERN.finditer(text):
        ref = match.group(0)
        if is_reserved_reference_value(ref):
            continue
        state_key = _state_key_for_ref(ref)
        if state_key is not None:
            known_refs.setdefault(state_key, ref)


def _state_key_for_ref(ref: str) -> str | None:
    if ref.startswith("resume_profile_"):
        return "resume_profile_id"
    if ref.startswith("career_profile_"):
        return "career_profile_id"
    if ref.startswith("resume_version_"):
        return "resume_version_id"
    if ref.startswith("application_"):
        return "application_id"
    if ref.startswith("fit_"):
        return "job_fit_report_id"
    if ref.startswith("jd_"):
        return "jd_analysis_id"
    return None


def _missing_inputs(
    *,
    target_agent_id: str,
    known_refs: dict[str, str],
    provided_records: dict[str, Any],
    provided_artifacts: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    if target_agent_id == "resume_agent":
        if "resume_source_artifact_id" not in known_refs or not provided_artifacts:
            missing.append("resume_source_artifact")
        return missing
    if target_agent_id == "job_agent":
        if "jd_source_artifact_id" not in known_refs and "jd_analysis" not in provided_records:
            missing.append("jd_source_artifact_or_jd_analysis")
        if "resume_profile" not in provided_records:
            missing.append("resume_profile")
        if "career_profile" not in provided_records:
            missing.append("career_profile")
    return missing


def _reuse_policy(*, provided_artifacts: list[dict[str, Any]], provided_records: dict[str, Any]) -> dict[str, Any]:
    already_provided: list[str] = []
    read_once_if_full_text_required: list[str] = []
    for artifact in provided_artifacts:
        artifact_id = artifact.get("artifact_id")
        if not isinstance(artifact_id, str):
            continue
        key = f"session_read_artifact:{artifact_id}"
        if artifact.get("text_truncated") is True:
            read_once_if_full_text_required.append(key)
        else:
            already_provided.append(key)
    for record_type, record in provided_records.items():
        if not isinstance(record, dict):
            continue
        record_id = record.get("record_id")
        tool_name = _get_tool_for_record_type(record_type)
        if isinstance(record_id, str) and tool_name is not None:
            already_provided.append(f"{tool_name}:{record_id}")
    return _drop_empty(
        {
            "already_provided": already_provided,
            "read_once_if_full_text_required": read_once_if_full_text_required,
        }
    )


def _get_tool_for_record_type(record_type: str) -> str | None:
    return {
        "resume_profile": "career_resume_profile_get",
        "career_profile": "career_profile_get",
        "jd_analysis": "career_jd_analysis_get",
        "job_fit_report": "career_job_fit_report_get",
        "career_application": "career_application_get",
    }.get(record_type)


def _phase_for_agent(target_agent_id: str) -> str:
    if target_agent_id == "resume_agent":
        return "resume_diagnosis"
    if target_agent_id == "job_agent":
        return "jd_fit"
    return "delegated_task"


def _required_outputs_for_agent(target_agent_id: str) -> list[str]:
    if target_agent_id == "resume_agent":
        return ["resume_profile", "diagnosis_artifact"]
    if target_agent_id == "job_agent":
        return ["jd_analysis", "job_fit_report", "report_artifact", "career_application"]
    return []


def _allowed_initial_tools_for_agent(target_agent_id: str) -> list[str]:
    if target_agent_id == "resume_agent":
        return ["career_resume_profile_save", "session_create_text_artifact"]
    if target_agent_id == "job_agent":
        return [
            "career_jd_analysis_save",
            "career_job_fit_report_save",
            "session_create_text_artifact",
            "career_application_create",
        ]
    return []


def _bounded_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _iso(value)
    if is_dataclass(value):
        return {
            field.name: _bounded_value(getattr(value, field.name), depth=depth + 1)
            for field in fields(value)
        }
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for index, (raw_key, raw_value) in enumerate(value.items()):
            if index >= _DICT_ITEMS or depth >= 5:
                output["_truncated_keys"] = max(0, len(value) - index)
                break
            output[str(raw_key)] = _bounded_value(raw_value, depth=depth + 1)
        return output
    if isinstance(value, list):
        items = [_bounded_value(item, depth=depth + 1) for item in value[:_LIST_ITEMS]]
        if len(value) > _LIST_ITEMS:
            items.append({"_truncated_items": len(value) - _LIST_ITEMS})
        return items
    if isinstance(value, str):
        return _truncate_inline(value, _RECORD_STRING_CHARS)
    return value


def _drop_empty(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _truncate_text(text: str, limit: int) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "\n...(truncated)"


def _truncate_inline(text: str, limit: int) -> str:
    normalized = " ".join(text.strip().split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "...(truncated)"


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _hash_text(payload)


def _field_iso(record: Any, field_name: str) -> str | None:
    value = getattr(record, field_name, None)
    return _iso(value) if isinstance(value, datetime) else None


def _iso(value: datetime) -> str:
    return value.isoformat()
