"""Central tool capability classification for runtime policy boundaries."""

from __future__ import annotations

from typing import Literal

__all__ = [
    "ACTION_WRITE_TOOL_NAMES",
    "READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES",
    "TOOL_KIND_IDEMPOTENT_WRITE_TOOL_NAMES",
    "TOOL_KIND_READ_ONLY_TOOL_NAMES",
    "TOOL_KIND_SCHEMA_TOOL_NAMES",
    "TOOL_KIND_VOLATILE_WRITE_TOOL_NAMES",
    "ToolKind",
    "is_write_tool",
    "tool_kind",
    "tool_names_for_kind",
]

ToolKind = Literal["schema", "read_only", "idempotent_write", "volatile_write", "unknown"]

TOOL_KIND_SCHEMA_TOOL_NAMES = ("tool_search",)

TOOL_KIND_READ_ONLY_TOOL_NAMES = (
    "session_read_artifact",
    "session_list_artifacts",
    "session_plan_artifact_access",
    "session_search_artifact",
    "career_resume_profile_get",
    "career_resume_profile_list",
    "career_profile_get",
    "career_jd_analysis_get",
    "career_jd_analysis_list",
    "career_job_fit_report_get",
    "career_job_fit_report_list",
    "career_application_get",
    "career_application_list",
    "career_resume_version_get",
    "career_resume_version_list",
    "retrieval_search",
    "retrieval_context_pack",
    "agent_task_status",
)

TOOL_KIND_IDEMPOTENT_WRITE_TOOL_NAMES = (
    "delegate_agents",
    "session_create_text_artifact",
    "career_resume_profile_save",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
    "career_application_create",
    "career_application_merge",
    "career_resume_version_create",
    "learning_task_create",
    "note_create",
    "note_append",
)

TOOL_KIND_VOLATILE_WRITE_TOOL_NAMES = ("memory_write",)

ACTION_WRITE_TOOL_NAMES = (
    "memory_write",
    "note_create",
    "note_append",
    "learning_task_create",
    "career_application_create",
    "career_application_merge",
    "career_resume_version_create",
    "career_resume_profile_save",
    "career_profile_merge",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
)

READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES = (
    "memory_write",
    "session_create_text_artifact",
    "career_resume_profile_save",
    "career_profile_merge",
    "career_jd_analysis_save",
    "career_job_fit_report_save",
    "career_application_create",
    "career_application_merge",
    "career_resume_version_create",
    "note_create",
    "note_append",
    "note_update",
    "learning_task_create",
    "learning_task_update_state",
    "learning_checkin_create",
)

_TOOL_NAMES_BY_KIND: dict[ToolKind, tuple[str, ...]] = {
    "schema": TOOL_KIND_SCHEMA_TOOL_NAMES,
    "read_only": TOOL_KIND_READ_ONLY_TOOL_NAMES,
    "idempotent_write": TOOL_KIND_IDEMPOTENT_WRITE_TOOL_NAMES,
    "volatile_write": TOOL_KIND_VOLATILE_WRITE_TOOL_NAMES,
    "unknown": (),
}
_TOOL_KIND_BY_NAME: dict[str, ToolKind] = {
    tool_name: kind
    for kind, tool_names in _TOOL_NAMES_BY_KIND.items()
    if kind != "unknown"
    for tool_name in tool_names
}
_WRITE_TOOL_NAMES = {
    *TOOL_KIND_IDEMPOTENT_WRITE_TOOL_NAMES,
    *TOOL_KIND_VOLATILE_WRITE_TOOL_NAMES,
    *ACTION_WRITE_TOOL_NAMES,
    *READ_ONLY_TURN_WRITE_BLOCK_TOOL_NAMES,
}


def tool_kind(tool_name: str) -> ToolKind:
    return _TOOL_KIND_BY_NAME.get(tool_name, "unknown")


def tool_names_for_kind(kind: ToolKind) -> tuple[str, ...]:
    return _TOOL_NAMES_BY_KIND[kind]


def is_write_tool(tool_name: str) -> bool:
    return tool_name in _WRITE_TOOL_NAMES
