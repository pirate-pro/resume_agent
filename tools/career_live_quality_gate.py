"""Live-smoke quality checks for career workflow outputs.

The checker is intentionally outside the runtime path. It reads durable session
artifacts, product records, and event logs, then flags high-confidence source
drift in user-visible outputs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from app.career.models import CareerApplication, CareerProfile, JDAnalysis, JobFitReport, ResumeProfile, ResumeVersion
from app.career.store import CareerProductStore
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository

__all__ = [
    "LiveQualityFinding",
    "LiveQualityReport",
    "check_career_live_quality",
]


@dataclass(slots=True)
class LiveQualityFinding:
    severity: str
    code: str
    message: str
    reference: str | None = None

    def format(self) -> str:
        parts = [self.severity, self.code]
        if self.reference:
            parts.append(self.reference)
        return f"{' / '.join(parts)}: {self.message}"


@dataclass(slots=True)
class LiveQualityReport:
    session_id: str
    findings: list[LiveQualityFinding] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)


@dataclass(frozen=True, slots=True)
class _DriftSignal:
    code: str
    markers: tuple[str, ...]
    message_label: str


_DRIFT_SIGNALS = (
    _DriftSignal(
        code="cpp",
        markers=("c++", "c＋＋", "cpp", "c plus plus"),
        message_label="C++",
    ),
    _DriftSignal(
        code="game_backend",
        markers=("游戏服务端", "游戏服务器", "游戏后端", "游戏开发"),
        message_label="游戏服务端",
    ),
)
_CAREER_PROFILE_TECH_SIGNALS = (
    _DriftSignal(code="java", markers=("java",), message_label="Java"),
    _DriftSignal(code="sql", markers=("sql",), message_label="SQL"),
    _DriftSignal(code="spark", markers=("spark",), message_label="Spark"),
    _DriftSignal(code="hadoop", markers=("hadoop",), message_label="Hadoop"),
    _DriftSignal(code="rna_seq", markers=("rna-seq", "rnaseq", "转录组"), message_label="RNA-seq"),
)
_GENERATED_ARTIFACT_KINDS = {"generated_file", "assistant_generated", "report", "markdown"}
_CANDIDATE_DEGREE_MARKERS = (
    "博士",
    "硕士",
    "研究生",
    "本科",
    "大专",
    "专科",
    "gpa",
    "绩点",
    "奖学金",
    "三好学生",
    "优秀毕业生",
)
_SCHOOL_PATTERN = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9（）()·]{2,}(?:大学|学院|学校|University|College|Institute)")


def check_career_live_quality(
    *,
    repository: JsonlSessionRepository,
    career_store: CareerProductStore,
    session_id: str,
) -> LiveQualityReport:
    """Check high-confidence source drift for one live-smoke session."""

    findings: list[LiveQualityFinding] = []
    artifact_texts = _artifact_texts(repository, session_id)
    source_corpus = _source_corpus(repository=repository, career_store=career_store, session_id=session_id)

    _check_jd_analysis_records(
        career_store=career_store,
        session_id=session_id,
        artifact_texts=artifact_texts,
        findings=findings,
    )
    _check_job_fit_records(
        career_store=career_store,
        session_id=session_id,
        artifact_texts=artifact_texts,
        findings=findings,
    )
    _check_career_profiles(
        career_store=career_store,
        session_id=session_id,
        artifact_texts=artifact_texts,
        findings=findings,
    )
    _check_resume_versions(
        career_store=career_store,
        session_id=session_id,
        source_corpus=source_corpus,
        artifact_texts=artifact_texts,
        findings=findings,
    )
    _check_user_visible_outputs(
        repository=repository,
        session_id=session_id,
        source_corpus=source_corpus,
        artifact_texts=artifact_texts,
        findings=findings,
    )
    return LiveQualityReport(session_id=session_id, findings=findings)


def _check_jd_analysis_records(
    *,
    career_store: CareerProductStore,
    session_id: str,
    artifact_texts: dict[str, str],
    findings: list[LiveQualityFinding],
) -> None:
    for record in career_store.list_jd_analyses(include_archived=True):
        if record.source_session_id != session_id:
            continue
        source_text = artifact_texts.get(record.source_artifact_id or "", "")
        if not source_text:
            continue
        text = _record_text(
            record.position,
            record.required_skills,
            record.preferred_skills,
            record.responsibilities,
            record.keywords,
            record.interview_focus,
        )
        unsupported = _unsupported_signals(text, source_text)
        if unsupported:
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="jd_analysis_source_drift",
                    reference=record.jd_analysis_id,
                    message=f"JDAnalysis 出现源 JD 不支持的强特征: {', '.join(unsupported)}。",
                )
            )


def _check_job_fit_records(
    *,
    career_store: CareerProductStore,
    session_id: str,
    artifact_texts: dict[str, str],
    findings: list[LiveQualityFinding],
) -> None:
    jd_by_id = {
        item.jd_analysis_id: item
        for item in career_store.list_jd_analyses(include_archived=True)
        if item.source_session_id == session_id
    }
    resume_by_id = {
        item.resume_profile_id: item
        for item in career_store.list_resume_profiles(include_archived=True)
        if item.source_session_id == session_id
    }
    for record in career_store.list_job_fit_reports(include_archived=True):
        if record.source_session_id != session_id:
            continue
        jd_record = jd_by_id.get(record.jd_analysis_id)
        resume_record = resume_by_id.get(record.resume_profile_id)
        source_text = "\n".join(
            item
            for item in [
                artifact_texts.get(record.source_artifact_id or "", ""),
                artifact_texts.get((jd_record.source_artifact_id if jd_record else None) or "", ""),
                artifact_texts.get((resume_record.source_artifact_id if resume_record else None) or "", ""),
            ]
            if item
        )
        if not source_text:
            continue
        text = _record_text(
            record.score_breakdown,
            record.matched_evidence,
            record.gaps,
            record.resume_optimization_direction,
            record.interview_preparation_focus,
        )
        unsupported = _unsupported_signals(text, source_text)
        if unsupported:
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="job_fit_report_source_drift",
                    reference=record.job_fit_report_id,
                    message=f"JobFitReport 出现源材料不支持的强特征: {', '.join(unsupported)}。",
                )
            )


def _check_career_profiles(
    *,
    career_store: CareerProductStore,
    session_id: str,
    artifact_texts: dict[str, str],
    findings: list[LiveQualityFinding],
) -> None:
    resume_by_id = {
        item.resume_profile_id: item
        for item in career_store.list_resume_profiles(include_archived=True)
        if item.source_session_id == session_id
    }
    for record in career_store.list_career_profiles(include_archived=True):
        if record.source_session_id != session_id:
            continue
        source_parts: list[str] = []
        for ref in record.evidence_refs:
            if ref.startswith("artifact_"):
                source_parts.append(artifact_texts.get(ref, ""))
            resume = resume_by_id.get(ref)
            if resume is not None:
                source_parts.append(artifact_texts.get(resume.source_artifact_id or "", ""))
                source_parts.append(_record_text(resume))
        if record.source_artifact_id:
            source_parts.append(artifact_texts.get(record.source_artifact_id, ""))
        source_text = "\n".join(item for item in source_parts if item)
        if not source_text:
            continue
        fact_text = _record_text(
            record.career_goal,
            record.target_roles,
            record.strengths,
            record.skills,
            record.education_summary,
            record.experience_summary,
        )
        unsupported = _unsupported_candidate_fact_markers(fact_text, source_text)
        if unsupported:
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="career_profile_source_drift",
                    reference=record.career_profile_id,
                    message=f"CareerProfile 出现源简历不支持的候选人事实: {', '.join(unsupported)}。",
                )
            )


def _check_resume_versions(
    *,
    career_store: CareerProductStore,
    session_id: str,
    source_corpus: str,
    artifact_texts: dict[str, str],
    findings: list[LiveQualityFinding],
) -> None:
    for record in career_store.list_resume_versions(include_archived=True):
        if record.source_session_id != session_id:
            continue
        text = _record_text(
            record.title,
            record.change_summary,
            record.keyword_strategy,
            artifact_texts.get(record.artifact_id, ""),
        )
        unsupported = _unsupported_signals(text, source_corpus)
        if unsupported:
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="resume_version_source_drift",
                    reference=record.resume_version_id,
                    message=f"ResumeVersion 出现源材料不支持的强特征: {', '.join(unsupported)}。",
                )
            )


def _check_user_visible_outputs(
    *,
    repository: JsonlSessionRepository,
    session_id: str,
    source_corpus: str,
    artifact_texts: dict[str, str],
    findings: list[LiveQualityFinding],
) -> None:
    for reference, text in _assistant_output_texts(repository, session_id):
        unsupported = _unsupported_signals(text, source_corpus)
        if _is_high_confidence_output_drift(text, unsupported):
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="final_answer_source_drift",
                    reference=reference,
                    message=f"用户可见答复出现源材料不支持的强特征: {', '.join(unsupported)}。",
                )
            )
    for artifact in repository.list_session_artifacts(session_id):
        if artifact.kind not in _GENERATED_ARTIFACT_KINDS:
            continue
        text = artifact_texts.get(artifact.artifact_id, "")
        unsupported = _unsupported_signals(text, source_corpus)
        if _is_high_confidence_output_drift(text, unsupported):
            findings.append(
                LiveQualityFinding(
                    severity="error",
                    code="generated_artifact_source_drift",
                    reference=artifact.artifact_id,
                    message=f"生成 artifact 出现源材料不支持的强特征: {', '.join(unsupported)}。",
                )
            )


def _source_corpus(
    *,
    repository: JsonlSessionRepository,
    career_store: CareerProductStore,
    session_id: str,
) -> str:
    source_artifact_parts = list(_source_artifact_texts(repository, session_id).values())
    if source_artifact_parts:
        return "\n".join(source_artifact_parts)
    parts: list[str] = []
    for record in _career_records(career_store, session_id):
        parts.append(_record_text(record))
    return "\n".join(parts)


def _career_records(career_store: CareerProductStore, session_id: str) -> list[
    ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication
]:
    output: list[ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion | CareerApplication] = []
    output.extend(
        record for record in career_store.list_resume_profiles(include_archived=True) if record.source_session_id == session_id
    )
    output.extend(
        record for record in career_store.list_career_profiles(include_archived=True) if record.source_session_id == session_id
    )
    output.extend(
        record for record in career_store.list_jd_analyses(include_archived=True) if record.source_session_id == session_id
    )
    output.extend(
        record
        for record in career_store.list_job_fit_reports(include_archived=True)
        if record.source_session_id == session_id
    )
    output.extend(
        record for record in career_store.list_resume_versions(include_archived=True) if record.source_session_id == session_id
    )
    output.extend(
        record
        for record in career_store.list_career_applications(include_archived=True)
        if record.source_session_id == session_id
    )
    return output


def _artifact_texts(repository: JsonlSessionRepository, session_id: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for artifact in repository.list_session_artifacts(session_id):
        if artifact.status != "ready" or artifact.text_relpath is None:
            continue
        try:
            output[artifact.artifact_id] = repository.read_session_artifact_text(session_id, artifact.artifact_id)
        except Exception:  # noqa: BLE001
            continue
    return output


def _source_artifact_texts(repository: JsonlSessionRepository, session_id: str) -> dict[str, str]:
    all_texts = _artifact_texts(repository, session_id)
    output: dict[str, str] = {}
    for artifact in repository.list_session_artifacts(session_id):
        if artifact.kind in _GENERATED_ARTIFACT_KINDS:
            continue
        text = all_texts.get(artifact.artifact_id)
        if text:
            output[artifact.artifact_id] = text
    return output


def _assistant_output_texts(repository: JsonlSessionRepository, session_id: str) -> Iterable[tuple[str, str]]:
    for event in _all_relevant_events(repository, session_id):
        if event.type not in {"assistant_message", "agent_result_summary"}:
            continue
        payload = event.payload if isinstance(event.payload, dict) else {}
        candidates = [payload.get("content"), payload.get("summary"), payload.get("answer")]
        text = "\n".join(str(item) for item in candidates if item)
        if text:
            yield event.event_id, text


def _all_relevant_events(repository: JsonlSessionRepository, session_id: str) -> list[Any]:
    events = repository.list_orchestration_events(session_id)
    for agent_id in _session_agent_ids(repository, session_id):
        events.extend(repository.list_agent_events(session_id, agent_id))
    output: list[Any] = []
    seen_event_ids: set[str] = set()
    for event in events:
        event_id = getattr(event, "event_id", "")
        if event_id in seen_event_ids:
            continue
        seen_event_ids.add(event_id)
        output.append(event)
    return output


def _session_agent_ids(repository: JsonlSessionRepository, session_id: str) -> list[str]:
    root = repository.get_session_root_path(session_id)
    agent_ids = {"agent_main"}
    agents_dir = root / "agents"
    if agents_dir.exists():
        for child in agents_dir.iterdir():
            if child.is_dir() and (child / "events.jsonl").exists():
                agent_ids.add(child.name)
    meta = repository.get_session(session_id)
    if meta is not None and meta.entry_agent_id:
        agent_ids.add(meta.entry_agent_id)
    return sorted(agent_ids)


def _unsupported_signals(text: str, source_text: str) -> list[str]:
    normalized_text = _normalize_text(text)
    normalized_source = _normalize_text(source_text)
    unsupported: list[str] = []
    for signal in _DRIFT_SIGNALS:
        if not any(marker in normalized_text for marker in signal.markers):
            continue
        if any(marker in normalized_source for marker in signal.markers):
            continue
        unsupported.append(signal.message_label)
    return unsupported


def _unsupported_candidate_fact_markers(text: str, source_text: str) -> list[str]:
    unsupported = _unsupported_signals(text, source_text)
    unsupported.extend(_unsupported_signal_group(text, source_text, _CAREER_PROFILE_TECH_SIGNALS))
    normalized_text = _normalize_text(text)
    normalized_source = _normalize_text(source_text)
    for marker in _CANDIDATE_DEGREE_MARKERS:
        normalized_marker = _normalize_text(marker)
        if normalized_marker in normalized_text and normalized_marker not in normalized_source:
            unsupported.append(marker)
    for school in _SCHOOL_PATTERN.findall(text):
        if _normalize_text(school) not in normalized_source:
            unsupported.append(school)
    return list(dict.fromkeys(unsupported))


def _unsupported_signal_group(text: str, source_text: str, signals: tuple[_DriftSignal, ...]) -> list[str]:
    normalized_text = _normalize_text(text)
    normalized_source = _normalize_text(source_text)
    unsupported: list[str] = []
    for signal in signals:
        if not any(marker in normalized_text for marker in signal.markers):
            continue
        if any(marker in normalized_source for marker in signal.markers):
            continue
        unsupported.append(signal.message_label)
    return unsupported


def _is_high_confidence_output_drift(text: str, unsupported: list[str]) -> bool:
    if not unsupported:
        return False
    normalized = _normalize_text(text)
    if "游戏服务端" in unsupported:
        return True
    return "C++" in unsupported and any(marker in normalized for marker in ("岗位", "职位", "jd", "服务端", "后端"))


def _record_text(*values: Any) -> str:
    parts: list[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            parts.append(value)
            continue
        try:
            parts.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        except (TypeError, ValueError):
            parts.append(str(value))
    return "\n".join(parts)


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().replace("ｃ", "c").split())
