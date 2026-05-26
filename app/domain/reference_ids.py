"""Shared reference-id filtering helpers."""

from __future__ import annotations

__all__ = ["is_reserved_reference_value"]

_RESERVED_REFERENCE_VALUES = {
    "application_id",
    "application_create",
    "application_get",
    "application_list",
    "application_merge",
    "application_save",
    "application_update",
    "artifact_id",
    "artifact_refs",
    "career_profile_get",
    "career_profile_id",
    "career_profile_list",
    "career_profile_merge",
    "career_profile_save",
    "career_profile_update",
    "diagnosis_artifact_id",
    "evidence_refs",
    "fit_score",
    "jd_analysis",
    "jd_analysis_get",
    "jd_analysis_id",
    "jd_analysis_list",
    "jd_analysis_save",
    "job_fit_report_get",
    "job_fit_report_id",
    "job_fit_report_list",
    "job_fit_report_save",
    "output_artifact_refs",
    "product_refs",
    "raw_text_artifact_id",
    "record_id",
    "report_artifact_id",
    "resume_profile_get",
    "resume_profile_id",
    "resume_profile_list",
    "resume_profile_save",
    "resume_version_get",
    "resume_version_id",
    "resume_version_list",
    "resume_version_create",
    "source_artifact_id",
}


def is_reserved_reference_value(value: str) -> bool:
    """Return true when a ref-like string is really a schema or tool token."""

    text = value.strip()
    return (
        text in _RESERVED_REFERENCE_VALUES
        or text.endswith("_stop_low_level_actions")
        or text.startswith("resume_version_artifact_")
    )
