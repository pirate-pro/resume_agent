"""Shared reference-id filtering helpers."""

from __future__ import annotations

__all__ = ["is_reserved_reference_value"]

_RESERVED_REFERENCE_VALUES = {
    "application_id",
    "artifact_id",
    "artifact_refs",
    "career_profile_get",
    "career_profile_id",
    "career_profile_merge",
    "career_profile_update",
    "diagnosis_artifact_id",
    "evidence_refs",
    "fit_score",
    "jd_analysis",
    "jd_analysis_id",
    "job_fit_report_id",
    "output_artifact_refs",
    "product_refs",
    "raw_text_artifact_id",
    "record_id",
    "report_artifact_id",
    "resume_profile_id",
    "resume_version_id",
    "source_artifact_id",
}


def is_reserved_reference_value(value: str) -> bool:
    """Return true when a ref-like string is really a schema or tool token."""

    text = value.strip()
    return text in _RESERVED_REFERENCE_VALUES or text.endswith("_stop_low_level_actions")
