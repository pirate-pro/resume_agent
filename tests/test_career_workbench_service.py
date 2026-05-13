"""Tests for the read-only career workbench service."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.career.workbench import CareerWorkbenchService
from app.learning.models import (
    LearningPlan,
    LearningRecordStatus,
    LearningTask,
    ReviewSchedule,
    WeaknessTracker,
)
from app.learning.store import LearningStore
from app.notes.models import Note, NoteRecordStatus, NoteSourceRef, NoteSourceType
from app.notes.store import NoteStore

__all__ = []


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 13, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def test_career_workbench_service_aggregates_application_context_without_writes(tmp_path: Path) -> None:
    career_store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    _seed_records(career_store, note_store, learning_store)
    service = CareerWorkbenchService(
        career_store=career_store,
        note_store=note_store,
        learning_store=learning_store,
    )
    before = _snapshot_json(tmp_path)

    detail = service.get_application_workbench("application_alpha")
    listing = service.list_workbench()

    assert _snapshot_json(tmp_path) == before
    assert detail is not None
    assert detail.application.application_id == "application_alpha"
    assert detail.resume_profile is not None
    assert detail.career_profile is not None
    assert detail.jd_analysis is not None
    assert detail.job_fit_report is not None
    assert [version.resume_version_id for version in detail.resume_versions] == ["resume_version_alpha"]
    assert [note.note_id for note in detail.notes] == ["note_alpha"]
    assert [plan.learning_plan_id for plan in detail.learning.plans] == ["learning_plan_alpha"]
    assert [task.learning_task_id for task in detail.learning.tasks] == ["learning_task_alpha"]
    assert [weakness.weakness_id for weakness in detail.learning.weaknesses] == ["weakness_alpha"]
    assert [review.review_schedule_id for review in detail.learning.reviews] == ["review_alpha"]
    assert detail.readiness.score == 82
    assert detail.readiness.level == "ready"
    assert "RAG 经验表达需要补证据" in detail.readiness.risks
    assert "简历画像" not in detail.readiness.missing_materials
    assert {asset.type for asset in detail.linked_assets} >= {
        "resume_profile",
        "career_profile",
        "jd_analysis",
        "job_fit_report",
        "resume_version",
        "note",
    }
    assert any(action.action_type == "pre_apply_check" for action in detail.suggested_actions)
    assert all("path" not in asset.actions for asset in detail.linked_assets)
    assert listing.active_application_id == "application_alpha"
    assert listing.counts.applications == 1
    assert listing.counts.notes == 1
    assert listing.counts.learning_tasks == 1


def test_career_workbench_service_filters_archived_applications_by_default(tmp_path: Path) -> None:
    career_store = CareerProductStore(root_dir=tmp_path / "career", clock=_TickingClock())
    note_store = NoteStore(root_dir=tmp_path / "notes", clock=_TickingClock())
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    _seed_records(career_store, note_store, learning_store)
    career_store.archive_career_application("application_alpha")
    service = CareerWorkbenchService(
        career_store=career_store,
        note_store=note_store,
        learning_store=learning_store,
    )

    assert service.get_application_workbench("application_alpha") is None
    assert service.list_workbench().applications == []
    assert service.get_application_workbench("application_alpha", include_archived=True) is not None
    assert service.list_workbench(include_archived=True).counts.applications == 1


def _seed_records(
    career_store: CareerProductStore,
    note_store: NoteStore,
    learning_store: LearningStore,
) -> None:
    career_store.save_resume_profile(_resume_profile())
    career_store.save_career_profile(_career_profile())
    career_store.save_jd_analysis(_jd_analysis())
    career_store.save_job_fit_report(_job_fit_report())
    career_store.save_resume_version(_resume_version())
    career_store.save_career_application(_career_application())
    note_store.save_note(_note())
    learning_store.save_learning_plan(_learning_plan())
    learning_store.save_learning_task(_learning_task())
    learning_store.save_weakness_tracker(_weakness())
    learning_store.save_review_schedule(_review())


def _resume_profile() -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id="resume_profile_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume",
        evidence_refs=["artifact_resume"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        basic_info={"name": "候选人"},
        skills=["Python", "FastAPI"],
        raw_text_artifact_id="artifact_resume",
        diagnosis_artifact_id="artifact_resume_diagnosis",
        diagnosis={"strengths": ["后端工程经验扎实"]},
    )


def _career_profile() -> CareerProfile:
    return CareerProfile(
        career_profile_id="career_profile_default",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["resume_profile_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        career_goal="AI 应用开发",
        target_roles=["后端开发"],
        strengths=["系统设计"],
        resume_issues=["RAG 指标证据不足"],
    )


def _jd_analysis() -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id="jd_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["artifact_jd"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company="Example Co",
        position="AI 应用开发工程师",
        required_skills=["Python", "RAG"],
        risk_signals=["需要讲清楚 RAG 生产实践"],
    )


def _job_fit_report() -> JobFitReport:
    return JobFitReport(
        job_fit_report_id="fit_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "artifact_jd"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        jd_analysis_id="jd_alpha",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        overall_score=82,
        matched_evidence=["Python 后端经验匹配"],
        gaps=["RAG 经验表达需要补证据"],
        resume_optimization_direction=["补充 RAG 项目量化指标"],
        interview_preparation_focus=["准备 RAG 评估方案"],
        recommendation="recommended",
        report_artifact_id="artifact_fit_report",
    )


def _resume_version() -> ResumeVersion:
    return ResumeVersion(
        resume_version_id="resume_version_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume_version",
        evidence_refs=["resume_profile_alpha", "jd_alpha", "fit_alpha", "artifact_resume_version"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        base_resume_profile_id="resume_profile_alpha",
        target_jd_analysis_id="jd_alpha",
        title="AI 应用开发简历版本",
        format="markdown",
        artifact_id="artifact_resume_version",
        change_summary=["强化 RAG 项目"],
    )


def _career_application() -> CareerApplication:
    return CareerApplication(
        application_id="application_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_jd",
        evidence_refs=["resume_profile_alpha", "career_profile_default", "jd_alpha", "fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company="Example Co",
        position="AI 应用开发工程师",
        location="上海",
        stage="ready_to_apply",
        priority="high",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        jd_analysis_id="jd_alpha",
        job_fit_report_id="fit_alpha",
        resume_version_ids=["resume_version_alpha"],
        summary="匹配度较高，适合优先投递。",
        next_actions=["完善 RAG 面试题"],
        risks=["RAG 经验表达需要补证据"],
    )


def _note() -> Note:
    return Note(
        note_id="note_alpha",
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["application_alpha", "fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="星河智能面试准备笔记",
        body_markdown="# 面试准备\n\n补充 RAG 评估方案。",
        tags=["RAG"],
        source_refs=[
            NoteSourceRef(
                source_type=NoteSourceType.CAREER_APPLICATION,
                source_id="application_alpha",
                source_session_id="sess_alpha",
                title="求职项目",
            )
        ],
        related_application_id="application_alpha",
        summary="围绕 RAG 评估准备回答。",
    )


def _learning_plan() -> LearningPlan:
    return LearningPlan(
        learning_plan_id="learning_plan_alpha",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["application_alpha", "fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="星河智能面试准备计划",
        plan_type="interview_prep",
        target_application_id="application_alpha",
        target_role="AI 应用开发工程师",
        target_company="Example Co",
        priority="high",
        task_ids=["learning_task_alpha"],
        weakness_ids=["weakness_alpha"],
        review_schedule_ids=["review_alpha"],
    )


def _learning_task() -> LearningTask:
    return LearningTask(
        learning_task_id="learning_task_alpha",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["learning_plan_alpha", "application_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="准备 RAG 评估回答",
        learning_plan_id="learning_plan_alpha",
        task_type="write_answer",
        priority="high",
        state="todo",
        skill_tags=["RAG"],
        estimated_minutes=45,
    )


def _weakness() -> WeaknessTracker:
    return WeaknessTracker(
        weakness_id="weakness_alpha",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["fit_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="RAG 深度不足",
        weakness_type="skill_gap",
        severity="high",
        state="open",
        skill_tags=["RAG"],
        target_application_ids=["application_alpha"],
        source_report_ids=["fit_alpha", "artifact_fit_report"],
        related_task_ids=["learning_task_alpha"],
        related_note_ids=["note_alpha"],
    )


def _review() -> ReviewSchedule:
    return ReviewSchedule(
        review_schedule_id="review_alpha",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["learning_task_alpha", "weakness_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title="复盘 RAG 回答",
        learning_plan_id="learning_plan_alpha",
        learning_task_id="learning_task_alpha",
        weakness_id="weakness_alpha",
        review_type="interview_rehearsal",
        state="scheduled",
    )


def _seed_time() -> datetime:
    return datetime(2026, 5, 13, 0, 0, tzinfo=UTC)


def _snapshot_json(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for path in sorted(root.rglob("*.json"))
    }
