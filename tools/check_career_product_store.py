"""Career product store consistency checker.

Run:
  uv run python tools/check_career_product_store.py --data-dir data/live_career_smoke/run_001
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence, TypeVar

from app.career.models import CareerProfile, JDAnalysis, JobFitReport, ResumeProfile, ResumeVersion
from app.career.store import CareerProductStore
from app.core.errors import AppError, StorageError
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository

__all__ = [
    "CareerStoreCheckFinding",
    "CareerStoreCheckReport",
    "check_career_product_store",
    "main",
]

CareerRecord = ResumeProfile | CareerProfile | JDAnalysis | JobFitReport | ResumeVersion
_RecordT = TypeVar("_RecordT", bound=CareerRecord)


@dataclass(slots=True)
class CareerStoreCheckFinding:
    """One consistency issue found in a career product store."""

    severity: str
    code: str
    message: str
    record_type: str | None = None
    record_id: str | None = None
    reference: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "reference": self.reference,
        }

    def format(self) -> str:
        parts = [self.severity, self.code]
        if self.record_type is not None:
            parts.append(self.record_type)
        if self.record_id is not None:
            parts.append(self.record_id)
        if self.reference is not None:
            parts.append(self.reference)
        return f"{' / '.join(parts)}: {self.message}"


@dataclass(slots=True)
class CareerStoreCheckReport:
    """Summary of career product store consistency checks."""

    data_dir: Path
    career_dir: Path
    session_id: str | None
    counts: dict[str, int]
    findings: list[CareerStoreCheckFinding] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def to_payload(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "data_dir": str(self.data_dir),
            "career_dir": str(self.career_dir),
            "session_id": self.session_id,
            "counts": self.counts,
            "findings": [item.to_payload() for item in self.findings],
        }


@dataclass(slots=True)
class _CareerRecords:
    resume_profiles: list[ResumeProfile]
    career_profiles: list[CareerProfile]
    jd_analyses: list[JDAnalysis]
    job_fit_reports: list[JobFitReport]
    resume_versions: list[ResumeVersion]

    def all_records(self) -> list[CareerRecord]:
        return [
            *self.resume_profiles,
            *self.career_profiles,
            *self.jd_analyses,
            *self.job_fit_reports,
            *self.resume_versions,
        ]


@dataclass(slots=True)
class _ArtifactIndex:
    session_ids: set[str]
    artifact_ids: set[str]
    artifact_to_session: dict[str, str]
    available: bool


def check_career_product_store(
    data_dir: Path,
    *,
    session_id: str | None = None,
    include_archived: bool = False,
) -> CareerStoreCheckReport:
    """Check career product records against session artifacts and product refs."""

    resolved_data_dir = _resolve_data_dir(data_dir)
    findings: list[CareerStoreCheckFinding] = []
    artifact_index = _load_artifact_index(
        resolved_data_dir,
        session_id=session_id,
        findings=findings,
    )
    career_dir = resolved_data_dir / "career"
    records = _load_records(
        career_dir=career_dir,
        include_archived=include_archived,
        findings=findings,
    )
    scoped_records = _filter_records_by_session(
        records,
        session_id=session_id,
        artifact_to_session=artifact_index.artifact_to_session,
    )

    _check_record_sources(scoped_records, artifact_index, findings)
    _check_direct_references(scoped_records, artifact_index, findings)
    _check_evidence_references(scoped_records, artifact_index, findings)
    _check_duplicate_products(scoped_records, findings)

    counts = {
        "sessions": len(artifact_index.session_ids),
        "artifacts": len(artifact_index.artifact_ids),
        "resume_profiles": len(scoped_records.resume_profiles),
        "career_profiles": len(scoped_records.career_profiles),
        "jd_analyses": len(scoped_records.jd_analyses),
        "job_fit_reports": len(scoped_records.job_fit_reports),
        "resume_versions": len(scoped_records.resume_versions),
    }
    return CareerStoreCheckReport(
        data_dir=resolved_data_dir,
        career_dir=career_dir,
        session_id=session_id,
        counts=counts,
        findings=findings,
    )


def _resolve_data_dir(data_dir: Path) -> Path:
    if data_dir.name == "career" and not (data_dir / "sessions").exists():
        return data_dir.parent
    return data_dir


def _load_artifact_index(
    data_dir: Path,
    *,
    session_id: str | None,
    findings: list[CareerStoreCheckFinding],
) -> _ArtifactIndex:
    sessions_dir = data_dir / "sessions"
    if not sessions_dir.exists():
        severity = "error" if session_id is not None else "warning"
        findings.append(
            CareerStoreCheckFinding(
                severity=severity,
                code="no_session_artifacts",
                message="未找到 sessions/ 目录，跳过 artifact 存在性校验。",
                reference=session_id,
            )
        )
        return _ArtifactIndex(
            session_ids=set(),
            artifact_ids=set(),
            artifact_to_session={},
            available=False,
        )
    repository = JsonlSessionRepository(data_dir=data_dir)
    session_ids: list[str] = []
    try:
        if session_id is None:
            session_ids = [item.session_id for item in repository.list_sessions()]
        else:
            session = repository.get_session(session_id)
            if session is None:
                findings.append(
                    CareerStoreCheckFinding(
                        severity="error",
                        code="missing_session",
                        message=f"会话不存在: {session_id}",
                        reference=session_id,
                    )
                )
            else:
                session_ids = [session.session_id]
    except AppError as exc:
        findings.append(
            CareerStoreCheckFinding(
                severity="error",
                code="session_load_failed",
                message=f"读取 session 数据失败: {exc}",
                reference=session_id,
            )
        )

    artifact_ids: set[str] = set()
    artifact_to_session: dict[str, str] = {}
    for item_session_id in session_ids:
        try:
            artifacts = repository.list_session_artifacts(item_session_id)
        except AppError as exc:
            findings.append(
                CareerStoreCheckFinding(
                    severity="error",
                    code="artifact_manifest_load_failed",
                    message=f"读取 artifact 清单失败: {exc}",
                    reference=item_session_id,
                )
            )
            continue
        for artifact in artifacts:
            artifact_ids.add(artifact.artifact_id)
            artifact_to_session[artifact.artifact_id] = artifact.session_id

    if not session_ids:
        findings.append(
            CareerStoreCheckFinding(
                severity="warning",
                code="no_session_artifacts",
                message="未找到 session artifact 清单，跳过 artifact 存在性校验。",
            )
        )

    return _ArtifactIndex(
        session_ids=set(session_ids),
        artifact_ids=artifact_ids,
        artifact_to_session=artifact_to_session,
        available=bool(session_ids),
    )


def _load_records(
    *,
    career_dir: Path,
    include_archived: bool,
    findings: list[CareerStoreCheckFinding],
) -> _CareerRecords:
    if not career_dir.exists():
        findings.append(
            CareerStoreCheckFinding(
                severity="warning",
                code="no_career_store",
                message="未找到 career/ 目录，跳过产品记录校验。",
            )
        )
        return _CareerRecords(
            resume_profiles=[],
            career_profiles=[],
            jd_analyses=[],
            job_fit_reports=[],
            resume_versions=[],
        )
    store = CareerProductStore(root_dir=career_dir)
    return _CareerRecords(
        resume_profiles=_load_record_list(
            "resume_profile",
            lambda: store.list_resume_profiles(include_archived=include_archived),
            findings,
        ),
        career_profiles=_load_record_list(
            "career_profile",
            lambda: store.list_career_profiles(include_archived=include_archived),
            findings,
        ),
        jd_analyses=_load_record_list(
            "jd_analysis",
            lambda: store.list_jd_analyses(include_archived=include_archived),
            findings,
        ),
        job_fit_reports=_load_record_list(
            "job_fit_report",
            lambda: store.list_job_fit_reports(include_archived=include_archived),
            findings,
        ),
        resume_versions=_load_record_list(
            "resume_version",
            lambda: store.list_resume_versions(include_archived=include_archived),
            findings,
        ),
    )


def _load_record_list(
    record_type: str,
    loader: Callable[[], list[_RecordT]],
    findings: list[CareerStoreCheckFinding],
) -> list[_RecordT]:
    try:
        return loader()
    except StorageError as exc:
        findings.append(
            CareerStoreCheckFinding(
                severity="error",
                code="record_load_failed",
                message=f"读取 {record_type} 记录失败: {exc}",
                record_type=record_type,
            )
        )
        return []


def _filter_records_by_session(
    records: _CareerRecords,
    *,
    session_id: str | None,
    artifact_to_session: dict[str, str],
) -> _CareerRecords:
    if session_id is None:
        return records
    return _CareerRecords(
        resume_profiles=_filter_record_list(records.resume_profiles, session_id, artifact_to_session),
        career_profiles=_filter_record_list(records.career_profiles, session_id, artifact_to_session),
        jd_analyses=_filter_record_list(records.jd_analyses, session_id, artifact_to_session),
        job_fit_reports=_filter_record_list(records.job_fit_reports, session_id, artifact_to_session),
        resume_versions=_filter_record_list(records.resume_versions, session_id, artifact_to_session),
    )


def _filter_record_list(
    records: Sequence[_RecordT],
    session_id: str,
    artifact_to_session: dict[str, str],
) -> list[_RecordT]:
    return [
        record
        for record in records
        if _record_touches_session(record, session_id, artifact_to_session)
    ]


def _record_touches_session(record: CareerRecord, session_id: str, artifact_to_session: dict[str, str]) -> bool:
    if record.source_session_id == session_id:
        return True
    if record.source_artifact_id is not None and artifact_to_session.get(record.source_artifact_id) == session_id:
        return True
    for ref in record.evidence_refs:
        if ref.startswith("artifact_") and artifact_to_session.get(ref) == session_id:
            return True
    if isinstance(record, JobFitReport) and record.report_artifact_id is not None:
        return artifact_to_session.get(record.report_artifact_id) == session_id
    if isinstance(record, ResumeVersion):
        return artifact_to_session.get(record.artifact_id) == session_id
    return False


def _check_record_sources(
    records: _CareerRecords,
    artifact_index: _ArtifactIndex,
    findings: list[CareerStoreCheckFinding],
) -> None:
    if not artifact_index.available:
        return
    for record in records.all_records():
        record_type = _record_type(record)
        record_id = _record_id(record)
        if record.source_session_id not in artifact_index.session_ids:
            findings.append(
                CareerStoreCheckFinding(
                    severity="error",
                    code="missing_source_session",
                    message=f"source_session_id 不存在: {record.source_session_id}",
                    record_type=record_type,
                    record_id=record_id,
                    reference=record.source_session_id,
                )
            )
        _check_artifact_ref(
            record_type,
            record_id,
            "source_artifact_id",
            record.source_artifact_id,
            artifact_index,
            findings,
            expected_session_id=record.source_session_id,
        )


def _check_direct_references(
    records: _CareerRecords,
    artifact_index: _ArtifactIndex,
    findings: list[CareerStoreCheckFinding],
) -> None:
    product_ids = _product_id_index(records)

    for record in records.resume_profiles:
        _check_artifact_ref(
            "resume_profile",
            record.resume_profile_id,
            "raw_text_artifact_id",
            record.raw_text_artifact_id,
            artifact_index,
            findings,
            expected_session_id=record.source_session_id,
        )
        _check_artifact_ref(
            "resume_profile",
            record.resume_profile_id,
            "diagnosis_artifact_id",
            record.diagnosis_artifact_id,
            artifact_index,
            findings,
            expected_session_id=record.source_session_id,
        )

    for record in records.job_fit_reports:
        _check_product_ref(
            "job_fit_report",
            record.job_fit_report_id,
            "jd_analysis_id",
            record.jd_analysis_id,
            product_ids["jd_analysis"],
            findings,
        )
        _check_product_ref(
            "job_fit_report",
            record.job_fit_report_id,
            "resume_profile_id",
            record.resume_profile_id,
            product_ids["resume_profile"],
            findings,
        )
        _check_product_ref(
            "job_fit_report",
            record.job_fit_report_id,
            "career_profile_id",
            record.career_profile_id,
            product_ids["career_profile"],
            findings,
        )
        _check_artifact_ref(
            "job_fit_report",
            record.job_fit_report_id,
            "report_artifact_id",
            record.report_artifact_id,
            artifact_index,
            findings,
            expected_session_id=record.source_session_id,
        )

    for record in records.resume_versions:
        _check_product_ref(
            "resume_version",
            record.resume_version_id,
            "base_resume_profile_id",
            record.base_resume_profile_id,
            product_ids["resume_profile"],
            findings,
        )
        if record.target_jd_analysis_id is not None:
            _check_product_ref(
                "resume_version",
                record.resume_version_id,
                "target_jd_analysis_id",
                record.target_jd_analysis_id,
                product_ids["jd_analysis"],
                findings,
            )
        _check_artifact_ref(
            "resume_version",
            record.resume_version_id,
            "artifact_id",
            record.artifact_id,
            artifact_index,
            findings,
            expected_session_id=record.source_session_id,
        )
        if record.source_artifact_id is not None and record.source_artifact_id != record.artifact_id:
            findings.append(
                CareerStoreCheckFinding(
                    severity="error",
                    code="resume_version_source_artifact_mismatch",
                    message="ResumeVersion.source_artifact_id 应与 artifact_id 保持一致。",
                    record_type="resume_version",
                    record_id=record.resume_version_id,
                    reference=record.source_artifact_id,
                )
            )


def _check_evidence_references(
    records: _CareerRecords,
    artifact_index: _ArtifactIndex,
    findings: list[CareerStoreCheckFinding],
) -> None:
    product_ids = _product_id_index(records)
    for record in records.all_records():
        record_type = _record_type(record)
        record_id = _record_id(record)
        for ref in record.evidence_refs:
            if ref.startswith("artifact_"):
                _check_artifact_ref(
                    record_type,
                    record_id,
                    "evidence_refs",
                    ref,
                    artifact_index,
                    findings,
                    expected_session_id=None,
                )
            elif ref.startswith("sess_"):
                if artifact_index.available and ref not in artifact_index.session_ids:
                    findings.append(
                        CareerStoreCheckFinding(
                            severity="error",
                            code="missing_session_ref",
                            message=f"evidence_refs 指向不存在的 session: {ref}",
                            record_type=record_type,
                            record_id=record_id,
                            reference=ref,
                        )
                    )
            else:
                bucket = _product_bucket_for_ref(ref)
                if bucket is not None:
                    _check_product_ref(
                        record_type,
                        record_id,
                        "evidence_refs",
                        ref,
                        product_ids[bucket],
                        findings,
                    )


def _check_duplicate_products(
    records: _CareerRecords,
    findings: list[CareerStoreCheckFinding],
) -> None:
    _check_duplicate_key(
        "resume_profile",
        records.resume_profiles,
        "duplicate_resume_profile_source",
        "同一 session/source_artifact_id 下存在多个 ResumeProfile。",
        lambda item: (item.source_session_id, item.source_artifact_id) if item.source_artifact_id else None,
        lambda item: item.resume_profile_id,
        findings,
    )
    _check_duplicate_key(
        "jd_analysis",
        records.jd_analyses,
        "duplicate_jd_analysis_source",
        "同一 session/source_artifact_id 下存在多个 JDAnalysis。",
        lambda item: (item.source_session_id, item.source_artifact_id) if item.source_artifact_id else None,
        lambda item: item.jd_analysis_id,
        findings,
    )
    _check_duplicate_key(
        "job_fit_report",
        records.job_fit_reports,
        "duplicate_job_fit_report_input",
        "同一 session/JD/Resume/source_artifact_id 下存在多个 JobFitReport。",
        lambda item: (
            item.source_session_id,
            item.jd_analysis_id,
            item.resume_profile_id,
            item.source_artifact_id,
        )
        if item.source_artifact_id
        else None,
        lambda item: item.job_fit_report_id,
        findings,
    )
    _check_duplicate_key(
        "job_fit_report",
        records.job_fit_reports,
        "duplicate_job_fit_report_artifact",
        "同一 session/report_artifact_id 下存在多个 JobFitReport。",
        lambda item: (item.source_session_id, item.report_artifact_id) if item.report_artifact_id else None,
        lambda item: item.job_fit_report_id,
        findings,
    )
    _check_duplicate_key(
        "resume_version",
        records.resume_versions,
        "duplicate_resume_version_artifact",
        "同一 session/artifact_id 下存在多个 ResumeVersion。",
        lambda item: (item.source_session_id, item.artifact_id),
        lambda item: item.resume_version_id,
        findings,
    )
    _check_duplicate_key(
        "resume_version",
        records.resume_versions,
        "duplicate_resume_version_input",
        "同一 session/Resume/JD/title 下存在多个 ResumeVersion。",
        lambda item: (
            item.source_session_id,
            item.base_resume_profile_id,
            item.target_jd_analysis_id,
            item.title,
        ),
        lambda item: item.resume_version_id,
        findings,
    )


def _check_duplicate_key(
    record_type: str,
    records: Iterable[_RecordT],
    code: str,
    message: str,
    key_fn: Callable[[_RecordT], tuple[Any, ...] | None],
    id_fn: Callable[[_RecordT], str],
    findings: list[CareerStoreCheckFinding],
) -> None:
    groups: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    for record in records:
        key = key_fn(record)
        if key is None:
            continue
        groups[tuple(key)].append(id_fn(record))
    for key, record_ids in groups.items():
        if len(record_ids) <= 1:
            continue
        findings.append(
            CareerStoreCheckFinding(
                severity="error",
                code=code,
                message=f"{message} key={key} records={record_ids}",
                record_type=record_type,
                record_id=",".join(record_ids),
                reference=str(key),
            )
        )


def _check_artifact_ref(
    record_type: str,
    record_id: str,
    field_name: str,
    artifact_id: str | None,
    artifact_index: _ArtifactIndex,
    findings: list[CareerStoreCheckFinding],
    *,
    expected_session_id: str | None,
) -> None:
    if artifact_id is None or not artifact_index.available:
        return
    actual_session_id = artifact_index.artifact_to_session.get(artifact_id)
    if actual_session_id is None:
        findings.append(
            CareerStoreCheckFinding(
                severity="error",
                code="missing_artifact_ref",
                message=f"{field_name} 指向不存在的 artifact: {artifact_id}",
                record_type=record_type,
                record_id=record_id,
                reference=artifact_id,
            )
        )
        return
    if expected_session_id is not None and actual_session_id != expected_session_id:
        findings.append(
            CareerStoreCheckFinding(
                severity="error",
                code="artifact_session_mismatch",
                message=(
                    f"{field_name} 所属 session 与记录 source_session_id 不一致: "
                    f"artifact_session={actual_session_id}, source_session_id={expected_session_id}"
                ),
                record_type=record_type,
                record_id=record_id,
                reference=artifact_id,
            )
        )


def _check_product_ref(
    record_type: str,
    record_id: str,
    field_name: str,
    ref_id: str,
    existing_ids: set[str],
    findings: list[CareerStoreCheckFinding],
) -> None:
    if ref_id in existing_ids:
        return
    findings.append(
        CareerStoreCheckFinding(
            severity="error",
            code="missing_product_ref",
            message=f"{field_name} 指向不存在的产品记录: {ref_id}",
            record_type=record_type,
            record_id=record_id,
            reference=ref_id,
        )
    )


def _product_id_index(records: _CareerRecords) -> dict[str, set[str]]:
    return {
        "resume_profile": {item.resume_profile_id for item in records.resume_profiles},
        "career_profile": {item.career_profile_id for item in records.career_profiles},
        "jd_analysis": {item.jd_analysis_id for item in records.jd_analyses},
        "job_fit_report": {item.job_fit_report_id for item in records.job_fit_reports},
        "resume_version": {item.resume_version_id for item in records.resume_versions},
    }


def _product_bucket_for_ref(ref: str) -> str | None:
    if ref.startswith("resume_profile_"):
        return "resume_profile"
    if ref.startswith("career_profile_"):
        return "career_profile"
    if ref.startswith("jd_"):
        return "jd_analysis"
    if ref.startswith("fit_"):
        return "job_fit_report"
    if ref.startswith("resume_version_"):
        return "resume_version"
    return None


def _record_type(record: CareerRecord) -> str:
    if isinstance(record, ResumeProfile):
        return "resume_profile"
    if isinstance(record, CareerProfile):
        return "career_profile"
    if isinstance(record, JDAnalysis):
        return "jd_analysis"
    if isinstance(record, JobFitReport):
        return "job_fit_report"
    return "resume_version"


def _record_id(record: CareerRecord) -> str:
    if isinstance(record, ResumeProfile):
        return record.resume_profile_id
    if isinstance(record, CareerProfile):
        return record.career_profile_id
    if isinstance(record, JDAnalysis):
        return record.jd_analysis_id
    if isinstance(record, JobFitReport):
        return record.job_fit_report_id
    return record.resume_version_id


def _print_text_report(report: CareerStoreCheckReport) -> None:
    status = "通过" if report.success else "失败"
    print(f"CareerProductStore 一致性检查: {status}")
    print(f"data_dir: {report.data_dir}")
    print(f"career_dir: {report.career_dir}")
    if report.session_id is not None:
        print(f"session_id: {report.session_id}")
    print(f"counts: {json.dumps(report.counts, ensure_ascii=False, sort_keys=True)}")
    if report.findings:
        print("findings:")
        for finding in report.findings:
            print(f"  - {finding.format()}")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="检查 CareerProductStore 与 SessionArtifact 的引用一致性。")
    parser.add_argument("--data-dir", type=Path, required=True, help="数据根目录，包含 career/ 与 sessions/。")
    parser.add_argument("--session-id", type=str, default=None, help="只检查触达指定 session 的产品记录。")
    parser.add_argument("--include-archived", action="store_true", help="包含 archived 产品记录。")
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告。")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = check_career_product_store(
        args.data_dir,
        session_id=args.session_id,
        include_archived=args.include_archived,
    )
    if args.json:
        print(json.dumps(report.to_payload(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _print_text_report(report)
    return 0 if report.success else 1


if __name__ == "__main__":
    raise SystemExit(main())
