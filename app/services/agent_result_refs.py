"""Extract durable artifact and product references from child-agent output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import EventRecord
from app.domain.protocols import SessionRepository
from app.domain.reference_ids import is_reserved_reference_value

__all__ = ["AgentOutputRefs", "collect_agent_output_refs"]

_MAX_REFS_PER_KIND = 20

_PRODUCT_PATTERNS = (
    re.compile(r"\bresume_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bcareer_profile_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bjd_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bfit_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bresume_version_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
    re.compile(r"\bapplication_[A-Za-z0-9][A-Za-z0-9_-]*\b"),
)
_IGNORED_REF_VALUES = {
    "artifact_id",
    "artifact_refs",
    "output_artifact_refs",
    "resume_profile_id",
    "career_profile_id",
    "jd_analysis",
    "jd_analysis_id",
    "job_fit_report_id",
    "resume_version_id",
    "application_id",
    "product_refs",
}
_PRODUCED_ARTIFACT_FIELDS_BY_TOOL = {
    "session_create_text_artifact": {"artifact_id"},
    "career_resume_profile_save": {"diagnosis_artifact_id"},
    "career_job_fit_report_save": {"report_artifact_id"},
    "career_resume_version_create": {"artifact_id"},
    "learning_task_create": {"output_artifact_id"},
    "learning_task_update": {"output_artifact_id"},
    "note_create": {"artifact_id"},
    "note_update": {"artifact_id"},
}


@dataclass(slots=True)
class AgentOutputRefs:
    """References produced or confirmed by one child-agent run."""

    input_artifact_refs: list[str] = field(default_factory=list)
    output_artifact_refs: list[str] = field(default_factory=list)
    product_refs: list[str] = field(default_factory=list)

    @property
    def artifact_refs(self) -> list[str]:
        return _merge_unique(self.output_artifact_refs, self.input_artifact_refs)


def collect_agent_output_refs(
    *,
    session_repository: SessionRepository,
    session_id: str,
    agent_id: str,
    run_id: str,
    input_artifact_refs: list[str],
) -> AgentOutputRefs:
    """Collect refs from the durable child run events.

    The input refs are kept separate so the orchestrator can distinguish files
    handed to the child from reports/artifacts produced by the child.
    """

    input_refs = _normalize_refs(input_artifact_refs, prefix="artifact_")
    output_artifact_refs: list[str] = []
    product_refs: list[str] = []
    for event in session_repository.list_run_events(session_id, agent_id, run_id):
        if not _is_result_bearing_event(event):
            continue
        output_artifact_refs = _merge_unique(
            output_artifact_refs,
            _extract_produced_artifact_refs(event),
            limit=_MAX_REFS_PER_KIND,
        )
        for value in _event_values(event):
            product_refs = _merge_unique(product_refs, _extract_product_refs(value), limit=_MAX_REFS_PER_KIND)
    output_artifact_refs = [item for item in output_artifact_refs if item not in set(input_refs)]
    return AgentOutputRefs(
        input_artifact_refs=input_refs,
        output_artifact_refs=output_artifact_refs,
        product_refs=product_refs,
    )


def _is_result_bearing_event(event: EventRecord) -> bool:
    return event.type in {"tool_result", "assistant_message"}


def _event_values(event: EventRecord) -> list[Any]:
    payload = event.payload if isinstance(event.payload, dict) else {}
    if event.type == "tool_result":
        content = payload.get("content")
        values: list[Any] = [content]
        decoded = _decode_json(content)
        if decoded is not None:
            values.append(decoded)
        return values
    if event.type == "assistant_message":
        return [payload.get("content")]
    return [payload]


def _decode_json(value: Any) -> Any | None:
    if not isinstance(value, str):
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _extract_produced_artifact_refs(event: EventRecord) -> list[str]:
    if event.type != "tool_result":
        return []
    payload = event.payload if isinstance(event.payload, dict) else {}
    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return []
    field_names = _PRODUCED_ARTIFACT_FIELDS_BY_TOOL.get(tool_name)
    if not field_names:
        return []
    decoded = _decode_json(payload.get("content"))
    if decoded is None:
        return []
    return _normalize_refs(_collect_field_values(decoded, field_names), prefix="artifact_")


def _collect_field_values(value: Any, field_names: set[str]) -> list[str]:
    output: list[str] = []
    _collect_fields(value, field_names, output)
    return output


def _collect_fields(value: Any, field_names: set[str], output: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in field_names and isinstance(child, str):
                output.append(child)
            _collect_fields(child, field_names, output)
        return
    if isinstance(value, list):
        for child in value:
            _collect_fields(child, field_names, output)


def _extract_product_refs(value: Any) -> list[str]:
    refs: list[str] = []
    for text in _iter_text(value):
        for pattern in _PRODUCT_PATTERNS:
            refs = _merge_unique(refs, pattern.findall(text), limit=_MAX_REFS_PER_KIND)
    return refs


def _iter_text(value: Any) -> list[str]:
    output: list[str] = []
    _collect_text(value, output)
    return output


def _collect_text(value: Any, output: list[str]) -> None:
    if isinstance(value, str):
        output.append(value)
        return
    if isinstance(value, dict):
        for child in value.values():
            _collect_text(child, output)
        return
    if isinstance(value, list):
        for child in value:
            _collect_text(child, output)
        return
    if value is not None and isinstance(value, (int, float)):
        output.append(str(value))


def _normalize_refs(values: list[str], *, prefix: str) -> list[str]:
    output: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        if text.startswith(prefix):
            output = _merge_unique(output, [text], limit=_MAX_REFS_PER_KIND)
    return output


def _merge_unique(*groups: list[str], limit: int | None = None) -> list[str]:
    output: list[str] = []
    for group in groups:
        for value in group:
            if not isinstance(value, str):
                continue
            text = value.strip()
            if not text or text in _IGNORED_REF_VALUES or is_reserved_reference_value(text) or text in output:
                continue
            output.append(text)
            if limit is not None and len(output) >= limit:
                return output
    return output
