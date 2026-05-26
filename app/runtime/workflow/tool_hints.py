"""Model-facing required tool call hints derived from workflow refs."""

from __future__ import annotations

from typing import Any

__all__ = ["build_required_tool_call_hint"]


def build_required_tool_call_hint(required_tool: str | None, known_refs: dict[str, Any]) -> dict[str, Any] | None:
    if required_tool is None:
        return None
    if required_tool == "career_job_fit_report_save":
        return _job_fit_report_save_hint(known_refs)
    if required_tool == "career_resume_version_create":
        return _resume_version_create_hint(known_refs)
    if required_tool == "career_application_merge":
        return _application_merge_hint(known_refs)
    return None


def _job_fit_report_save_hint(known_refs: dict[str, Any]) -> dict[str, Any]:
    expected_args = [
        "jd_analysis_id",
        "resume_profile_id",
        "career_profile_id",
        "source_artifact_id",
        "report_artifact_id",
    ]
    available_args = {key: known_refs[key] for key in expected_args if _is_non_empty_string(known_refs.get(key))}
    available_args.setdefault("career_profile_id", "career_profile_default")
    missing_args = [key for key in expected_args if key not in available_args]
    return {
        "tool_name": "career_job_fit_report_save",
        "available_args": available_args,
        "missing_args": missing_args,
        "retry_tool_call_skeleton": available_args,
        "instruction": (
            "缺失参数若已在 assigned task、用户消息或刚才读取的记录中出现，直接复用；"
            "career_profile_id 缺失时使用 career_profile_default；不要 get/list 只为确认。"
        ),
    }


def _resume_version_create_hint(known_refs: dict[str, Any]) -> dict[str, Any]:
    resume_profile_id = _string_or_none(known_refs.get("resume_profile_id"))
    jd_analysis_id = _string_or_none(known_refs.get("jd_analysis_id"))
    evidence_refs = _dedupe_strings(
        [
            _string_or_none(known_refs.get("resume_profile_id")),
            _string_or_none(known_refs.get("career_profile_id")),
            _string_or_none(known_refs.get("jd_analysis_id")),
            _string_or_none(known_refs.get("job_fit_report_id")),
            _string_or_none(known_refs.get("report_artifact_id")),
            _string_or_none(known_refs.get("resume_source_artifact_id")),
            _string_or_none(known_refs.get("jd_source_artifact_id")),
        ]
    )
    available_args: dict[str, Any] = {
        "title": "定制简历",
    }
    if resume_profile_id is not None:
        available_args["base_resume_profile_id"] = resume_profile_id
    if jd_analysis_id is not None:
        available_args["target_jd_analysis_id"] = jd_analysis_id
    if evidence_refs:
        available_args["evidence_refs"] = evidence_refs
    missing_args = [
        key
        for key in ("base_resume_profile_id", "target_jd_analysis_id", "evidence_refs")
        if key not in available_args
    ]
    if _string_or_none(known_refs.get("resume_version_artifact_id")) is not None:
        available_args["artifact_id"] = _string_or_none(known_refs.get("resume_version_artifact_id"))
    else:
        missing_args.append("content_or_artifact_id")
    skeleton = dict(available_args)
    skeleton.setdefault("content", "<完整 Markdown 简历正文；不要写匹配报告、风险表或面试准备>")
    return {
        "tool_name": "career_resume_version_create",
        "available_args": available_args,
        "missing_args": missing_args,
        "retry_tool_call_skeleton": skeleton,
        "instruction": (
            "直接调用 career_resume_version_create。传完整 Markdown content，或传已有 generated_file artifact_id；"
            "不要再 tool_search/get/list。content 只写交付简历正文，不写 JD 匹配表、风险分析或面试准备。"
        ),
    }


def _application_merge_hint(known_refs: dict[str, Any]) -> dict[str, Any]:
    application_id = _string_or_none(known_refs.get("application_id"))
    resume_version_id = _string_or_none(known_refs.get("resume_version_id"))
    resume_version_artifact_id = _string_or_none(known_refs.get("resume_version_artifact_id")) or _string_or_none(
        known_refs.get("artifact_id")
    )
    available_args: dict[str, Any] = {}
    if application_id is not None:
        available_args["application_id"] = application_id
    if resume_version_id is not None:
        available_args["updates"] = {"resume_version_ids": [resume_version_id]}
    evidence_refs = _dedupe_strings([resume_version_id, resume_version_artifact_id])
    if evidence_refs:
        available_args["evidence_refs"] = evidence_refs
    if resume_version_artifact_id is not None:
        available_args["source_artifact_id"] = resume_version_artifact_id
    missing_args = []
    if application_id is None:
        missing_args.append("application_id")
    if resume_version_id is None:
        missing_args.append("resume_version_id")
    if not evidence_refs:
        missing_args.append("evidence_refs")
    return {
        "tool_name": "career_application_merge",
        "available_args": available_args,
        "missing_args": missing_args,
        "retry_tool_call_skeleton": available_args,
        "instruction": (
            "只调用 career_application_merge，把当前 resume_version_id 写入 updates.resume_version_ids；"
            "不要重新读取项目、不要重新创建 ResumeVersion、不要 tool_search。"
        ),
    }


def _string_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _is_non_empty_string(value: Any) -> bool:
    return _string_or_none(value) is not None


def _dedupe_strings(items: list[str | None]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item is None or item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
