"""Read-only aggregation service for the career workbench."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, TypeVar, cast

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
    validate_application_id,
)
from app.career.store import CareerProductStore
from app.learning.models import (
    LearningPlan,
    LearningTask,
    ReviewSchedule,
    WeaknessTracker,
)
from app.learning.store import LearningStore
from app.notes.models import Note, NoteSourceType, NoteType
from app.notes.store import NoteStore

__all__ = [
    "CareerApplicationSummary",
    "CareerApplicationWorkbench",
    "CareerLearningSummary",
    "CareerLinkedAsset",
    "CareerNoteSummary",
    "CareerReadiness",
    "CareerSuggestedAction",
    "CareerTimelineItem",
    "CareerWorkbenchCounts",
    "CareerWorkbenchList",
    "CareerWorkbenchService",
]

_RecordT = TypeVar("_RecordT")


@dataclass(slots=True)
class CareerReadiness:
    """Derived readiness information for one target application."""

    score: int | None
    level: str
    recommendation: str
    summary: str
    strengths: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    missing_materials: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CareerLinkedAsset:
    """Front-end friendly reference to a linked product asset."""

    type: str
    id: str
    title: str
    subtitle: str
    status: str
    updated_at: datetime | None = None
    preview_artifact_id: str | None = None
    source_session_id: str | None = None
    is_current: bool = False
    actions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CareerTimelineItem:
    """Timeline event generated from existing product records."""

    type: str
    title: str
    subtitle: str
    occurred_at: datetime
    source_type: str
    source_id: str


@dataclass(slots=True)
class CareerSuggestedAction:
    """Suggested next user action for a workbench."""

    action_type: str
    label: str
    prompt_intent: str
    priority: str = "medium"
    enabled: bool = True
    reason: str = ""


@dataclass(slots=True)
class CareerNoteSummary:
    """Compact note summary for the workbench detail view."""

    note_id: str
    title: str
    summary: str
    status: str
    updated_at: datetime
    note_type: str = "note"
    source_artifact_id: str | None = None
    related_application_id: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CareerLearningSummary:
    """Learning records explicitly linked to one application."""

    plans: list[LearningPlan] = field(default_factory=list)
    tasks: list[LearningTask] = field(default_factory=list)
    weaknesses: list[WeaknessTracker] = field(default_factory=list)
    reviews: list[ReviewSchedule] = field(default_factory=list)
    open_task_count: int = 0
    done_task_count: int = 0
    high_weakness_count: int = 0


@dataclass(slots=True)
class CareerApplicationSummary:
    """Summary row for the career workbench list."""

    application: CareerApplication
    readiness: CareerReadiness
    linked_asset_count: int
    note_count: int
    learning_task_count: int
    updated_at: datetime


@dataclass(slots=True)
class CareerWorkbenchCounts:
    """Aggregate counters for the workbench list."""

    applications: int = 0
    active_applications: int = 0
    notes: int = 0
    learning_tasks: int = 0
    resume_versions: int = 0


@dataclass(slots=True)
class CareerWorkbenchList:
    """Read-only career workbench list result."""

    applications: list[CareerApplicationSummary]
    active_application_id: str | None
    counts: CareerWorkbenchCounts
    updated_at: datetime | None


@dataclass(slots=True)
class CareerApplicationWorkbench:
    """Read-only career workbench detail result."""

    application: CareerApplication
    readiness: CareerReadiness
    linked_assets: list[CareerLinkedAsset]
    notes: list[CareerNoteSummary]
    learning: CareerLearningSummary
    timeline: list[CareerTimelineItem]
    suggested_actions: list[CareerSuggestedAction]
    resume_profile: ResumeProfile | None = None
    career_profile: CareerProfile | None = None
    jd_analysis: JDAnalysis | None = None
    job_fit_report: JobFitReport | None = None
    resume_versions: list[ResumeVersion] = field(default_factory=list)


@dataclass(slots=True)
class _ApplicationBundle:
    application: CareerApplication
    resume_profile: ResumeProfile | None
    career_profile: CareerProfile | None
    jd_analysis: JDAnalysis | None
    job_fit_report: JobFitReport | None
    resume_versions: list[ResumeVersion]
    notes: list[Note]
    learning_plans: list[LearningPlan]
    learning_tasks: list[LearningTask]
    weaknesses: list[WeaknessTracker]
    reviews: list[ReviewSchedule]


class CareerWorkbenchService:
    """Build read-only career workbench views from existing stores."""

    def __init__(
        self,
        *,
        career_store: CareerProductStore,
        note_store: NoteStore,
        learning_store: LearningStore,
    ) -> None:
        self._career_store = career_store
        self._note_store = note_store
        self._learning_store = learning_store

    def list_workbench(self, *, include_archived: bool = False) -> CareerWorkbenchList:
        applications = self._career_store.list_career_applications(include_archived=include_archived)
        bundles = [
            self._build_bundle(application, include_archived=include_archived)
            for application in applications
        ]
        summaries = [self._build_summary(bundle) for bundle in bundles]
        updated_at = _latest_datetime([summary.updated_at for summary in summaries])
        return CareerWorkbenchList(
            applications=summaries,
            active_application_id=_active_application_id(summaries),
            counts=CareerWorkbenchCounts(
                applications=len(summaries),
                active_applications=sum(
                    1
                    for item in summaries
                    if item.application.status == CareerRecordStatus.ACTIVE
                ),
                notes=sum(item.note_count for item in summaries),
                learning_tasks=sum(item.learning_task_count for item in summaries),
                resume_versions=sum(len(bundle.resume_versions) for bundle in bundles),
            ),
            updated_at=updated_at,
        )

    def get_application_workbench(
        self,
        application_id: str,
        *,
        include_archived: bool = False,
    ) -> CareerApplicationWorkbench | None:
        application = self._career_store.get_career_application(validate_application_id(application_id))
        if application is None or not _is_visible(application, include_archived=include_archived):
            return None
        bundle = self._build_bundle(application, include_archived=include_archived)
        readiness = _build_readiness(bundle)
        linked_assets = _build_linked_assets(bundle)
        learning = _build_learning_summary(bundle)
        return CareerApplicationWorkbench(
            application=bundle.application,
            resume_profile=bundle.resume_profile,
            career_profile=bundle.career_profile,
            jd_analysis=bundle.jd_analysis,
            job_fit_report=bundle.job_fit_report,
            resume_versions=bundle.resume_versions,
            readiness=readiness,
            linked_assets=linked_assets,
            notes=[_note_summary(note) for note in bundle.notes],
            learning=learning,
            timeline=_build_timeline(bundle),
            suggested_actions=_build_suggested_actions(bundle, readiness),
        )

    def _build_summary(self, bundle: _ApplicationBundle) -> CareerApplicationSummary:
        readiness = _build_readiness(bundle)
        linked_assets = _build_linked_assets(bundle)
        updated_at = _latest_datetime([
            bundle.application.updated_at,
            *(asset.updated_at for asset in linked_assets if asset.updated_at is not None),
            *(note.updated_at for note in bundle.notes),
            *(task.updated_at for task in bundle.learning_tasks),
        ])
        return CareerApplicationSummary(
            application=bundle.application,
            readiness=readiness,
            linked_asset_count=len(linked_assets),
            note_count=len(bundle.notes),
            learning_task_count=len(bundle.learning_tasks),
            updated_at=updated_at or bundle.application.updated_at,
        )

    def _build_bundle(self, application: CareerApplication, *, include_archived: bool) -> _ApplicationBundle:
        resume_profile = _visible_or_none(
            self._career_store.get_resume_profile(application.resume_profile_id)
            if application.resume_profile_id
            else None,
            include_archived=include_archived,
        )
        career_profile = _visible_or_none(
            self._career_store.get_career_profile(application.career_profile_id)
            if application.career_profile_id
            else None,
            include_archived=include_archived,
        )
        jd_analysis = _visible_or_none(
            self._career_store.get_jd_analysis(application.jd_analysis_id)
            if application.jd_analysis_id
            else None,
            include_archived=include_archived,
        )
        job_fit_report = _visible_or_none(
            self._career_store.get_job_fit_report(application.job_fit_report_id)
            if application.job_fit_report_id
            else None,
            include_archived=include_archived,
        )
        resume_versions = [
            item
            for item in (
                _visible_or_none(
                    self._career_store.get_resume_version(resume_version_id),
                    include_archived=include_archived,
                )
                for resume_version_id in application.resume_version_ids
            )
            if item is not None
        ]
        learning_plans = _learning_plans_for_application(
            self._learning_store,
            application.application_id,
            include_archived=include_archived,
        )
        learning_tasks = _learning_tasks_for_application(
            self._learning_store,
            application.application_id,
            {plan.learning_plan_id for plan in learning_plans},
            include_archived=include_archived,
        )
        weaknesses = _weaknesses_for_application(
            self._learning_store,
            application.application_id,
            application.job_fit_report_id,
            include_archived=include_archived,
        )
        reviews = _reviews_for_learning(
            self._learning_store,
            plan_ids={plan.learning_plan_id for plan in learning_plans},
            task_ids={task.learning_task_id for task in learning_tasks},
            weakness_ids={weakness.weakness_id for weakness in weaknesses},
            include_archived=include_archived,
        )
        return _ApplicationBundle(
            application=application,
            resume_profile=resume_profile,
            career_profile=career_profile,
            jd_analysis=jd_analysis,
            job_fit_report=job_fit_report,
            resume_versions=resume_versions,
            notes=_notes_for_application(
                self._note_store,
                application.application_id,
                include_archived=include_archived,
            ),
            learning_plans=learning_plans,
            learning_tasks=learning_tasks,
            weaknesses=weaknesses,
            reviews=reviews,
        )


def _build_readiness(bundle: _ApplicationBundle) -> CareerReadiness:
    fit = bundle.job_fit_report
    score = fit.overall_score if fit is not None else None
    missing_materials = _missing_materials(bundle)
    risks = _dedupe_text([
        *bundle.application.risks,
        *_text_list(fit.gaps if fit is not None else []),
        *(bundle.jd_analysis.risk_signals if bundle.jd_analysis is not None else []),
    ], limit=8)
    strengths = _dedupe_text([
        *_text_list(fit.matched_evidence if fit is not None else []),
        *(bundle.career_profile.strengths if bundle.career_profile is not None else []),
        *_text_list(_diagnosis_values(bundle.resume_profile, "strengths")),
    ], limit=8)
    next_actions = _readiness_next_actions(bundle, missing_materials)
    return CareerReadiness(
        score=score,
        level=_readiness_level(score),
        recommendation=fit.recommendation if fit is not None else "unknown",
        summary=_readiness_summary(bundle, score),
        strengths=strengths,
        risks=risks,
        missing_materials=missing_materials,
        next_actions=next_actions,
    )


def _build_linked_assets(bundle: _ApplicationBundle) -> list[CareerLinkedAsset]:
    assets: list[CareerLinkedAsset] = []
    if bundle.resume_profile is not None:
        resume = bundle.resume_profile
        assets.append(
            CareerLinkedAsset(
                type="resume_profile",
                id=resume.resume_profile_id,
                title=_resume_title(resume),
                subtitle="简历画像",
                status=_enum_value(resume.status),
                updated_at=resume.updated_at,
                preview_artifact_id=(
                    resume.diagnosis_artifact_id
                    or resume.raw_text_artifact_id
                    or resume.source_artifact_id
                ),
                source_session_id=resume.source_session_id,
                is_current=True,
                actions=["detail", "preview"],
            )
        )
    if bundle.career_profile is not None:
        profile = bundle.career_profile
        assets.append(
            CareerLinkedAsset(
                type="career_profile",
                id=profile.career_profile_id,
                title=profile.career_goal or _first_text(profile.target_roles) or "职业画像",
                subtitle="职业画像",
                status=_enum_value(profile.status),
                updated_at=profile.updated_at,
                preview_artifact_id=profile.source_artifact_id,
                source_session_id=profile.source_session_id,
                is_current=True,
                actions=["detail"],
            )
        )
    if bundle.jd_analysis is not None:
        jd = bundle.jd_analysis
        assets.append(
            CareerLinkedAsset(
                type="jd_analysis",
                id=jd.jd_analysis_id,
                title=_job_title(jd.company, jd.position, fallback="JD 分析"),
                subtitle="岗位分析",
                status=_enum_value(jd.status),
                updated_at=jd.updated_at,
                preview_artifact_id=jd.source_artifact_id,
                source_session_id=jd.source_session_id,
                is_current=True,
                actions=["detail", "preview"],
            )
        )
    if bundle.job_fit_report is not None:
        report = bundle.job_fit_report
        assets.append(
            CareerLinkedAsset(
                type="job_fit_report",
                id=report.job_fit_report_id,
                title=_job_title(
                    bundle.application.company,
                    bundle.application.position,
                    fallback="匹配报告",
                ),
                subtitle=f"匹配度 {report.overall_score}/100",
                status=_enum_value(report.status),
                updated_at=report.updated_at,
                preview_artifact_id=report.report_artifact_id,
                source_session_id=report.source_session_id,
                is_current=True,
                actions=["detail", "preview"],
            )
        )
    latest_resume_version_id = _latest_resume_version_id(bundle.resume_versions)
    for version in bundle.resume_versions:
        assets.append(
            CareerLinkedAsset(
                type="resume_version",
                id=version.resume_version_id,
                title=version.title,
                subtitle="定制简历",
                status=_enum_value(version.status),
                updated_at=version.updated_at,
                preview_artifact_id=version.artifact_id,
                source_session_id=version.source_session_id,
                is_current=version.resume_version_id == latest_resume_version_id,
                actions=["preview", "download"],
            )
        )
    for note in bundle.notes:
        assets.append(
            CareerLinkedAsset(
                type="note",
                id=note.note_id,
                title=note.title,
                subtitle="笔记",
                status=_enum_value(note.status),
                updated_at=note.updated_at,
                preview_artifact_id=note.source_artifact_id,
                source_session_id=note.source_session_id,
                actions=["detail"],
            )
        )
    return assets


def _build_learning_summary(bundle: _ApplicationBundle) -> CareerLearningSummary:
    open_states = {"todo", "doing", "blocked"}
    return CareerLearningSummary(
        plans=bundle.learning_plans,
        tasks=bundle.learning_tasks,
        weaknesses=bundle.weaknesses,
        reviews=bundle.reviews,
        open_task_count=sum(1 for task in bundle.learning_tasks if _enum_value(task.state) in open_states),
        done_task_count=sum(1 for task in bundle.learning_tasks if _enum_value(task.state) == "done"),
        high_weakness_count=sum(1 for weakness in bundle.weaknesses if _enum_value(weakness.severity) == "high"),
    )


def _build_timeline(bundle: _ApplicationBundle) -> list[CareerTimelineItem]:
    items = [
        CareerTimelineItem(
            type="application",
            title="求职项目更新",
            subtitle=_job_title(bundle.application.company, bundle.application.position, fallback="求职项目"),
            occurred_at=bundle.application.updated_at,
            source_type="career_application",
            source_id=bundle.application.application_id,
        )
    ]
    if bundle.resume_profile is not None:
        items.append(
            _timeline_item(
                "resume_profile",
                "简历画像更新",
                bundle.resume_profile.resume_profile_id,
                bundle.resume_profile.updated_at,
            )
        )
    if bundle.jd_analysis is not None:
        items.append(
            _timeline_item(
                "jd_analysis",
                "岗位分析更新",
                bundle.jd_analysis.jd_analysis_id,
                bundle.jd_analysis.updated_at,
            )
        )
    if bundle.job_fit_report is not None:
        items.append(
            _timeline_item(
                "job_fit_report",
                "匹配报告更新",
                bundle.job_fit_report.job_fit_report_id,
                bundle.job_fit_report.updated_at,
            )
        )
    for version in bundle.resume_versions:
        items.append(_timeline_item("resume_version", version.title, version.resume_version_id, version.updated_at))
    for note in bundle.notes:
        items.append(_timeline_item("note", note.title, note.note_id, note.updated_at))
    for plan in bundle.learning_plans:
        items.append(_timeline_item("learning_plan", plan.title, plan.learning_plan_id, plan.updated_at))
    for task in bundle.learning_tasks:
        items.append(_timeline_item("learning_task", task.title, task.learning_task_id, task.updated_at))
    for weakness in bundle.weaknesses:
        items.append(_timeline_item("weakness", weakness.title, weakness.weakness_id, weakness.updated_at))
    for review in bundle.reviews:
        items.append(_timeline_item("review", review.title, review.review_schedule_id, review.updated_at))
    items.sort(key=lambda item: item.occurred_at, reverse=True)
    return items[:50]


def _build_suggested_actions(
    bundle: _ApplicationBundle,
    readiness: CareerReadiness,
) -> list[CareerSuggestedAction]:
    actions: list[CareerSuggestedAction] = []
    if bundle.resume_profile is None:
        actions.append(
            _action(
                "resume_diagnosis",
                "生成简历画像",
                "分析当前简历并生成简历画像",
                "high",
                True,
                "当前项目还缺少简历画像",
            )
        )
    if bundle.jd_analysis is None:
        actions.append(
            _action(
                "jd_analysis",
                "分析岗位 JD",
                "分析当前目标岗位 JD",
                "high",
                True,
                "当前项目还缺少 JD 分析",
            )
        )
    if bundle.job_fit_report is None and bundle.resume_profile is not None and bundle.jd_analysis is not None:
        actions.append(
            _action(
                "job_fit_report",
                "生成匹配报告",
                "基于当前简历画像和 JD 生成岗位匹配报告",
                "high",
                True,
                "已有简历和 JD，可以生成匹配报告",
            )
        )
    if bundle.job_fit_report is not None:
        actions.extend(
            [
                _action(
                    "pre_apply_check",
                    "投递前检查",
                    "基于当前求职项目做投递前检查",
                    "high",
                    True,
                    "复用当前匹配报告和求职项目",
                ),
                _action(
                    "custom_resume",
                    "生成定制简历",
                    "基于当前岗位生成定制简历版本",
                    "high",
                    True,
                    "已有匹配报告，可以定制简历",
                ),
                _action(
                    "interview_prep",
                    "准备面试",
                    "基于当前岗位和短板生成面试准备建议",
                    "medium",
                    True,
                    "复用匹配报告、笔记和学习任务",
                ),
                _action(
                    "learning_task",
                    "创建学习任务",
                    "基于当前短板创建学习任务",
                    "medium",
                    True,
                    "把短板拆成可执行任务",
                ),
            ]
        )
    if not bundle.notes:
        actions.append(
            _action(
                "save_note",
                "保存笔记",
                "把这次求职准备内容保存为笔记",
                "low",
                True,
                "当前项目还没有关联笔记",
            )
        )
    if not actions and readiness.next_actions:
        actions.append(
            _action(
                "next_action",
                "继续推进",
                readiness.next_actions[0],
                "medium",
                True,
                "来自当前项目下一步行动",
            )
        )
    return actions


def _notes_for_application(store: NoteStore, application_id: str, *, include_archived: bool) -> list[Note]:
    notes = store.list_notes(include_archived=include_archived)
    return [
        note
        for note in notes
        if note.related_application_id == application_id
        or application_id in note.evidence_refs
        or any(
            _enum_value(source_ref.source_type) == NoteSourceType.CAREER_APPLICATION.value
            and source_ref.source_id == application_id
            for source_ref in note.source_refs
        )
    ]


def _learning_plans_for_application(
    store: LearningStore,
    application_id: str,
    *,
    include_archived: bool,
) -> list[LearningPlan]:
    return [
        plan
        for plan in store.list_learning_plans(include_archived=include_archived)
        if plan.target_application_id == application_id or application_id in plan.evidence_refs
    ]


def _learning_tasks_for_application(
    store: LearningStore,
    application_id: str,
    plan_ids: set[str],
    *,
    include_archived: bool,
) -> list[LearningTask]:
    return [
        task
        for task in store.list_learning_tasks(include_archived=include_archived)
        if task.learning_plan_id in plan_ids or application_id in task.evidence_refs
    ]


def _weaknesses_for_application(
    store: LearningStore,
    application_id: str,
    job_fit_report_id: str | None,
    *,
    include_archived: bool,
) -> list[WeaknessTracker]:
    return [
        weakness
        for weakness in store.list_weakness_trackers(include_archived=include_archived)
        if application_id in weakness.target_application_ids
        or application_id in weakness.evidence_refs
        or (job_fit_report_id is not None and job_fit_report_id in weakness.source_report_ids)
    ]


def _reviews_for_learning(
    store: LearningStore,
    *,
    plan_ids: set[str],
    task_ids: set[str],
    weakness_ids: set[str],
    include_archived: bool,
) -> list[ReviewSchedule]:
    return [
        review
        for review in store.list_review_schedules(include_archived=include_archived)
        if review.learning_plan_id in plan_ids
        or review.learning_task_id in task_ids
        or review.weakness_id in weakness_ids
    ]


def _visible_or_none(record: _RecordT | None, *, include_archived: bool) -> _RecordT | None:
    if record is None:
        return None
    return record if _is_visible(record, include_archived=include_archived) else None


def _is_visible(record: object, *, include_archived: bool) -> bool:
    return include_archived or _enum_value(getattr(record, "status")) == "active"


def _note_summary(note: Note) -> CareerNoteSummary:
    return CareerNoteSummary(
        note_id=note.note_id,
        title=note.title,
        summary=note.summary,
        status=_enum_value(note.status),
        updated_at=note.updated_at,
        note_type=cast(NoteType, note.note_type).value,
        source_artifact_id=note.source_artifact_id,
        related_application_id=note.related_application_id,
        tags=note.tags,
    )


def _missing_materials(bundle: _ApplicationBundle) -> list[str]:
    missing: list[str] = []
    if bundle.resume_profile is None:
        missing.append("简历画像")
    if bundle.career_profile is None:
        missing.append("职业画像")
    if bundle.jd_analysis is None:
        missing.append("JD 分析")
    if bundle.job_fit_report is None:
        missing.append("匹配报告")
    if not bundle.resume_versions:
        missing.append("定制简历")
    return missing


def _readiness_next_actions(bundle: _ApplicationBundle, missing_materials: list[str]) -> list[str]:
    if bundle.application.next_actions:
        return _dedupe_text(bundle.application.next_actions, limit=8)
    actions: list[str] = []
    if "简历画像" in missing_materials:
        actions.append("先生成简历画像，作为后续匹配和定制简历的基础。")
    if "JD 分析" in missing_materials:
        actions.append("补齐目标岗位 JD 分析，明确硬性要求和面试重点。")
    if "匹配报告" in missing_materials and bundle.resume_profile is not None and bundle.jd_analysis is not None:
        actions.append("生成匹配报告，判断是否值得优先投递。")
    if bundle.job_fit_report is not None:
        actions.extend(_text_list(bundle.job_fit_report.resume_optimization_direction))
        actions.extend(_text_list(bundle.job_fit_report.interview_preparation_focus))
    return _dedupe_text(actions, limit=8)


def _readiness_summary(bundle: _ApplicationBundle, score: int | None) -> str:
    if bundle.application.summary:
        return bundle.application.summary
    if score is None:
        return "当前项目还没有完整匹配报告，建议先补齐简历画像、JD 分析和匹配报告。"
    recommendation = bundle.job_fit_report.recommendation if bundle.job_fit_report is not None else "unknown"
    if recommendation == "recommended":
        return f"当前匹配度 {score}/100，整体适合推进投递或面试准备。"
    if recommendation == "not_recommended":
        return f"当前匹配度 {score}/100，核心风险较高，建议先补齐关键短板。"
    return f"当前匹配度 {score}/100，具备一定基础，建议补齐短板后谨慎推进。"


def _readiness_level(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 85:
        return "strong"
    if score >= 70:
        return "ready"
    if score >= 60:
        return "needs_work"
    return "high_risk"


def _timeline_item(source_type: str, title: str, source_id: str, occurred_at: datetime) -> CareerTimelineItem:
    return CareerTimelineItem(
        type=source_type,
        title=title,
        subtitle="产品记录",
        occurred_at=occurred_at,
        source_type=source_type,
        source_id=source_id,
    )


def _action(
    action_type: str,
    label: str,
    prompt_intent: str,
    priority: str,
    enabled: bool,
    reason: str,
) -> CareerSuggestedAction:
    return CareerSuggestedAction(
        action_type=action_type,
        label=label,
        prompt_intent=prompt_intent,
        priority=priority,
        enabled=enabled,
        reason=reason,
    )


def _active_application_id(summaries: list[CareerApplicationSummary]) -> str | None:
    active_stages = {"draft", "analyzing", "ready_to_apply", "applied", "interviewing"}
    for summary in summaries:
        if summary.application.status == CareerRecordStatus.ACTIVE and summary.application.stage in active_stages:
            return summary.application.application_id
    return summaries[0].application.application_id if summaries else None


def _latest_datetime(values: list[datetime]) -> datetime | None:
    return max(values) if values else None


def _latest_resume_version_id(versions: list[ResumeVersion]) -> str | None:
    if not versions:
        return None
    latest = max(versions, key=lambda item: (item.updated_at, item.created_at))
    return latest.resume_version_id


def _resume_title(resume: ResumeProfile) -> str:
    raw_name = resume.basic_info.get("name")
    return raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else "简历画像"


def _job_title(company: str, position: str, *, fallback: str) -> str:
    parts = [item for item in (company.strip(), position.strip()) if item]
    return " · ".join(parts) if parts else fallback


def _first_text(values: list[str]) -> str:
    return values[0] if values else ""


def _diagnosis_values(resume: ResumeProfile | None, key: str) -> list[Any]:
    if resume is None:
        return []
    value = resume.diagnosis.get(key)
    return value if isinstance(value, list) else []


def _text_list(values: list[Any]) -> list[str]:
    output: list[str] = []
    for item in values:
        text = _text_item(item)
        if text:
            output.append(text)
    return output


def _text_item(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in (
            "title",
            "summary",
            "description",
            "gap",
            "risk",
            "issue",
            "action",
            "evidence",
            "text",
            "name",
        ):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        parts = [value.strip() for value in item.values() if isinstance(value, str) and value.strip()]
        return "；".join(parts[:3])
    return ""


def _dedupe_text(values: list[str], *, limit: int) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for raw in values:
        item = raw.strip()
        if not item or item in seen:
            continue
        output.append(item)
        seen.add(item)
        if len(output) >= limit:
            break
    return output


def _enum_value(value: Enum | str) -> str:
    if isinstance(value, str):
        return value
    return str(value.value)
