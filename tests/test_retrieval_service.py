"""Tests for rule-based RetrievalService."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
)
from app.career.store import CareerProductStore
from app.core.time import APP_TIMEZONE
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.knowledge.models import (
    CompanyProfile,
    ExternalResource,
    InterviewDifficulty,
    InterviewQuestion,
    KnowledgeRecordStatus,
    QuestionType,
    ResourceType,
    SkillCategory,
    SkillLevel,
    SkillRequirement,
)
from app.knowledge.store import KnowledgeStore
from app.learning.models import (
    LearningPlan,
    LearningPlanType,
    LearningPriority,
    LearningRecordStatus,
    LearningTask,
    LearningTaskState,
    LearningTaskType,
    WeaknessSeverity,
    WeaknessState,
    WeaknessTracker,
    WeaknessType,
)
from app.learning.store import LearningStore
from app.notes.models import Note, NoteRecordStatus, NoteSourceRef, NoteSourceType
from app.notes.store import NoteStore
from app.retrieval.models import RetrievalQuery, RetrievalSourceType
from app.retrieval.service import RetrievalService


@dataclass(slots=True)
class RetrievalStores:
    career: CareerProductStore
    notes: NoteStore
    knowledge: KnowledgeStore
    learning: LearningStore
    sessions: JsonlSessionRepository


def test_retrieval_searches_product_sources_and_builds_context_pack(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    service = _service(stores)

    request = RetrievalQuery(
        query="星河智能 RAG 二面准备",
        session_id="sess_alpha",
        top_k=20,
        max_chars=2000,
    )
    hits = service.search(request)
    source_types = {hit.source.source_type for hit in hits}
    pack = service.build_context_pack(request)

    assert RetrievalSourceType.CAREER_APPLICATION in source_types
    assert RetrievalSourceType.JOB_FIT_REPORT in source_types
    assert RetrievalSourceType.NOTE in source_types
    assert RetrievalSourceType.EXTERNAL_RESOURCE in source_types
    assert RetrievalSourceType.INTERVIEW_QUESTION in source_types
    assert RetrievalSourceType.LEARNING_TASK in source_types
    assert RetrievalSourceType.WEAKNESS_TRACKER in source_types
    assert RetrievalSourceType.SESSION_ARTIFACT in source_types
    assert hits[0].score >= hits[-1].score
    assert all(hit.source.source_id for hit in hits)
    assert all(hit.match_reason for hit in hits)
    assert pack.query == "星河智能 RAG 二面准备"
    assert pack.grouped_context["career"]
    assert pack.grouped_context["notes"]
    assert pack.grouped_context["knowledge"]
    assert pack.grouped_context["learning"]
    assert pack.grouped_context["artifacts"]
    assert {item.source_id for item in pack.citations} == {hit.source.source_id for hit in pack.hits}


def test_retrieval_respects_source_type_related_filter_and_archived_records(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    archived = _note("note_archived", related_application_id="application_alpha")
    stores.notes.save_note(archived)
    stores.notes.archive_note("note_archived")
    other = _note("note_beta", related_application_id="application_beta")
    other.title = "其他公司复盘"
    other.evidence_refs = ["application_beta", "artifact_note_beta"]
    stores.notes.save_note(other)
    service = _service(stores)

    active_request = RetrievalQuery(
        query="RAG 复盘",
        session_id="sess_alpha",
        source_types=[RetrievalSourceType.NOTE],
        related_application_id="application_alpha",
        top_k=10,
    )
    active_hits = service.search(active_request)
    archived_hits = service.search(
        RetrievalQuery(
            query="RAG 复盘",
            session_id="sess_alpha",
            source_types=["note"],
            related_application_id="application_alpha",
            include_archived=True,
            top_k=10,
        )
    )

    assert {hit.source.source_id for hit in active_hits} == {"note_rag_review"}
    assert {hit.source.source_id for hit in archived_hits} == {"note_rag_review", "note_archived"}


def test_context_pack_applies_budget_and_does_not_read_cross_session_artifacts(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    _add_artifact(stores.sessions, "sess_beta", "artifact_beta_rag", "星河智能 RAG 跨会话资料不应被当前会话召回")
    service = _service(stores)

    artifact_hits = service.search(
        RetrievalQuery(
            query="星河智能 RAG",
            session_id="sess_alpha",
            source_types=[RetrievalSourceType.SESSION_ARTIFACT],
            top_k=10,
        )
    )
    pack = service.build_context_pack(
        RetrievalQuery(
            query="星河智能 RAG",
            session_id="sess_alpha",
            source_types=[
                RetrievalSourceType.EXTERNAL_RESOURCE,
                RetrievalSourceType.INTERVIEW_QUESTION,
                RetrievalSourceType.SKILL_REQUIREMENT,
                RetrievalSourceType.COMPANY_PROFILE,
            ],
            top_k=2,
            max_chars=260,
            per_source_type_limit=1,
        )
    )

    assert {hit.source.source_id for hit in artifact_hits} == {"artifact_alpha_jd"}
    assert pack.hits
    assert pack.omitted
    assert sum(hit.content_length() for hit in pack.hits) <= 260
    assert all(hit.source.source_type != RetrievalSourceType.SESSION_ARTIFACT for hit in pack.omitted)
    assert not list((tmp_path / "career").rglob("*.md"))
    assert not list((tmp_path / "notes").rglob("*.md"))
    assert not list((tmp_path / "knowledge").rglob("*.md"))
    assert not list((tmp_path / "learning").rglob("*.md"))


def test_context_pack_expands_around_related_career_application(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    service = _service(stores)

    pack = service.build_context_pack(
        RetrievalQuery(
            query="今天怎么准备",
            session_id="sess_alpha",
            source_types=[
                RetrievalSourceType.CAREER_APPLICATION,
                RetrievalSourceType.RESUME_PROFILE,
                RetrievalSourceType.CAREER_PROFILE,
                RetrievalSourceType.JD_ANALYSIS,
                RetrievalSourceType.JOB_FIT_REPORT,
                RetrievalSourceType.RESUME_VERSION,
            ],
            related_application_id="application_alpha",
            top_k=10,
            max_chars=8000,
        )
    )
    source_ids = {hit.source.source_id for hit in pack.hits}

    assert {
        "application_alpha",
        "resume_profile_alpha",
        "career_profile_default",
        "jd_stargazer_backend",
        "fit_stargazer_backend",
    } <= source_ids


def _seed_stores(tmp_path: Path) -> RetrievalStores:
    stores = RetrievalStores(
        career=CareerProductStore(root_dir=tmp_path / "career"),
        notes=NoteStore(root_dir=tmp_path / "notes"),
        knowledge=KnowledgeStore(root_dir=tmp_path / "knowledge"),
        learning=LearningStore(root_dir=tmp_path / "learning"),
        sessions=JsonlSessionRepository(data_dir=tmp_path / "sessions"),
    )
    stores.sessions.create_session("sess_alpha")
    stores.sessions.create_session("sess_beta")
    _add_artifact(
        stores.sessions,
        "sess_alpha",
        "artifact_alpha_jd",
        "星河智能 AI Agent 后端二面会追问 RAG 检索评估、chunk 策略和异步任务。",
    )
    stores.career.save_resume_profile(_resume_profile())
    stores.career.save_career_profile(_career_profile())
    stores.career.save_jd_analysis(_jd_analysis())
    stores.career.save_job_fit_report(_fit_report())
    stores.career.save_career_application(_application())
    stores.notes.save_note(_note())
    stores.knowledge.save_external_resource(_resource())
    stores.knowledge.save_interview_question(_question())
    stores.knowledge.save_company_profile(_company())
    stores.knowledge.save_skill_requirement(_skill())
    stores.learning.save_learning_plan(_plan())
    stores.learning.save_learning_task(_task())
    stores.learning.save_weakness_tracker(_weakness())
    return stores


def _service(stores: RetrievalStores) -> RetrievalService:
    return RetrievalService(
        career_store=stores.career,
        note_store=stores.notes,
        knowledge_store=stores.knowledge,
        learning_store=stores.learning,
        session_repository=stores.sessions,
    )


def _now() -> datetime:
    return datetime(2026, 5, 12, 10, 0, tzinfo=APP_TIMEZONE)


def _add_artifact(repository: JsonlSessionRepository, session_id: str, artifact_id: str, text: str) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "original.txt").write_text(text, encoding="utf-8")
    (artifact_dir / "content.txt").write_text(text, encoding="utf-8")
    now = _now()
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind="uploaded_file",
            title="星河智能 JD.txt",
            media_type="text/plain",
            size_bytes=len(text.encode("utf-8")),
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=f"artifacts/{artifact_id}/original.txt",
            text_relpath=f"artifacts/{artifact_id}/content.txt",
            text_char_count=len(text),
            token_estimate=20,
            parsed_at=now,
        )
    )


def _resume_profile() -> ResumeProfile:
    return ResumeProfile(
        resume_profile_id="resume_profile_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resume_alpha",
        evidence_refs=["artifact_resume_alpha"],
        created_at=_now(),
        updated_at=_now(),
        basic_info={"name": "张明"},
        skills=["Python", "FastAPI", "RAG"],
        diagnosis={"gaps": ["RAG 项目证据不足"]},
    )


def _career_profile() -> CareerProfile:
    return CareerProfile(
        career_profile_id="career_profile_default",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id=None,
        evidence_refs=["resume_profile_alpha"],
        created_at=_now(),
        updated_at=_now(),
        career_goal="AI Agent 后端工程师",
        target_roles=["AI Agent 后端工程师"],
        skills=["Python", "FastAPI", "RAG"],
        interview_weaknesses=["RAG 检索评估表达薄弱"],
    )


def _jd_analysis() -> JDAnalysis:
    return JDAnalysis(
        jd_analysis_id="jd_stargazer_backend",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_alpha_jd",
        evidence_refs=["artifact_alpha_jd"],
        created_at=_now(),
        updated_at=_now(),
        company="星河智能",
        position="AI Agent 后端工程师",
        required_skills=["Python", "FastAPI", "RAG"],
        interview_focus=["RAG 检索评估", "多 Agent 编排", "异步任务"],
    )


def _fit_report() -> JobFitReport:
    return JobFitReport(
        job_fit_report_id="fit_stargazer_backend",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_alpha_jd",
        evidence_refs=[
            "application_alpha",
            "resume_profile_alpha",
            "career_profile_default",
            "jd_stargazer_backend",
            "artifact_fit_report_alpha",
        ],
        created_at=_now(),
        updated_at=_now(),
        jd_analysis_id="jd_stargazer_backend",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        overall_score=76,
        score_breakdown={"RAG": 62, "Agent": 78},
        matched_evidence=["Python FastAPI 后端经验"],
        gaps=["RAG 检索评估证据不足", "LangGraph 经验薄弱"],
        interview_preparation_focus=["RAG chunk 策略", "召回评估", "Agent Runtime 架构"],
        recommendation="cautious",
        report_artifact_id="artifact_fit_report_alpha",
    )


def _application() -> CareerApplication:
    return CareerApplication(
        application_id="application_alpha",
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_alpha_jd",
        evidence_refs=[
            "artifact_alpha_jd",
            "resume_profile_alpha",
            "career_profile_default",
            "jd_stargazer_backend",
            "fit_stargazer_backend",
        ],
        created_at=_now(),
        updated_at=_now(),
        company="星河智能",
        position="AI Agent 后端工程师",
        stage="interviewing",
        priority="high",
        resume_profile_id="resume_profile_alpha",
        career_profile_id="career_profile_default",
        jd_analysis_id="jd_stargazer_backend",
        job_fit_report_id="fit_stargazer_backend",
        summary="星河智能二面准备中，核心风险是 RAG 深度追问。",
        next_actions=["准备 RAG 检索评估回答", "复盘 Agent Runtime 架构"],
        risks=["RAG 深度不足"],
    )


def _note(note_id: str = "note_rag_review", *, related_application_id: str = "application_alpha") -> Note:
    return Note(
        note_id=note_id,
        status=NoteRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report_alpha",
        evidence_refs=[related_application_id, "fit_stargazer_backend", "artifact_fit_report_alpha"],
        created_at=_now(),
        updated_at=_now(),
        title="星河智能 RAG 二面复盘",
        body_markdown="## RAG 复盘\n需要讲清 chunk 策略、召回率、评估集和失败恢复。",
        tags=["RAG", "二面", "星河智能"],
        source_refs=[
            NoteSourceRef(
                source_type=NoteSourceType.CAREER_APPLICATION,
                source_id=related_application_id,
                source_session_id="sess_alpha",
                title="星河智能 AI Agent 后端工程师",
            )
        ],
        related_application_id=related_application_id,
        summary="二面前重点补 RAG 检索评估表达。",
    )


def _resource() -> ExternalResource:
    return ExternalResource(
        resource_id="resource_stargazer_interview",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_alpha",
        evidence_refs=["artifact_resource_alpha", "application_alpha"],
        created_at=_now(),
        updated_at=_now(),
        title="星河智能 AI Agent 后端面经",
        resource_type=ResourceType.PASTED_TEXT,
        company="星河智能",
        position="AI Agent 后端工程师",
        target_roles=["AI Agent 后端工程师"],
        skill_tags=["RAG", "Agent Runtime"],
        summary="二面重点是 RAG 检索评估和系统设计。",
        key_points=["RAG chunk 策略", "异步任务可靠性", "多 Agent 编排"],
        raw_artifact_id="artifact_resource_alpha",
        related_application_ids=["application_alpha"],
    )


def _question() -> InterviewQuestion:
    return InterviewQuestion(
        question_id="question_rag_chunk_strategy",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_alpha",
        evidence_refs=["resource_stargazer_interview", "application_alpha"],
        created_at=_now(),
        updated_at=_now(),
        question_text="RAG 的 chunk 策略如何设计，如何评估召回效果？",
        question_type=QuestionType.TECHNICAL,
        difficulty=InterviewDifficulty.HARD,
        skill_tags=["RAG", "向量检索"],
        company="星河智能",
        position="AI Agent 后端工程师",
        answer_outline="先讲切分粒度，再讲召回率、评估集和线上监控。",
        evaluation_points=["chunk 粒度", "召回率", "失败恢复"],
        related_application_ids=["application_alpha"],
    )


def _company() -> CompanyProfile:
    return CompanyProfile(
        company_id="company_stargazer",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_company_alpha",
        evidence_refs=["resource_stargazer_interview"],
        created_at=_now(),
        updated_at=_now(),
        company_name="星河智能",
        target_roles=["AI Agent 后端工程师"],
        hiring_signals=["项目深挖", "RAG 工程化"],
        interview_style="偏二面系统设计和项目深挖",
        common_questions=["RAG 评估", "异步任务设计"],
        resource_ids=["resource_stargazer_interview"],
        question_ids=["question_rag_chunk_strategy"],
        summary="关注 AI 应用工程化和稳定性。",
    )


def _skill() -> SkillRequirement:
    return SkillRequirement(
        skill_requirement_id="skill_req_rag_engineering",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_alpha",
        evidence_refs=["resource_stargazer_interview", "question_rag_chunk_strategy"],
        created_at=_now(),
        updated_at=_now(),
        skill_name="RAG 工程化",
        category=SkillCategory.RAG,
        level=SkillLevel.WORKING,
        description="能解释检索、切分、评估和线上稳定性。",
        assessment_points=["chunk 策略", "召回评估", "失败恢复"],
        role_tags=["AI Agent 后端工程师"],
        resource_ids=["resource_stargazer_interview"],
        question_ids=["question_rag_chunk_strategy"],
    )


def _plan() -> LearningPlan:
    return LearningPlan(
        learning_plan_id="learning_plan_stargazer",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report_alpha",
        evidence_refs=["application_alpha", "fit_stargazer_backend"],
        created_at=_now(),
        updated_at=_now(),
        title="星河智能二面学习计划",
        description="补齐 RAG 与 Agent Runtime 面试短板。",
        plan_type=LearningPlanType.INTERVIEW_PREP,
        target_application_id="application_alpha",
        target_role="AI Agent 后端工程师",
        target_company="星河智能",
        priority=LearningPriority.HIGH,
        goals=["准备 RAG 检索评估", "梳理多 Agent 架构"],
        focus_skill_tags=["RAG", "Agent Runtime"],
        task_ids=["learning_task_rag_eval"],
        weakness_ids=["weakness_rag_depth"],
    )


def _task() -> LearningTask:
    return LearningTask(
        learning_task_id="learning_task_rag_eval",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report_alpha",
        evidence_refs=["application_alpha", "learning_plan_stargazer", "resource_stargazer_interview"],
        created_at=_now(),
        updated_at=_now(),
        title="准备 RAG 检索评估回答",
        learning_plan_id="learning_plan_stargazer",
        description="写出 chunk 策略、召回评估和失败恢复回答。",
        task_type=LearningTaskType.WRITE_ANSWER,
        priority=LearningPriority.HIGH,
        state=LearningTaskState.TODO,
        skill_tags=["RAG"],
        resource_refs=["resource_stargazer_interview", "skill_req_rag_engineering"],
        question_refs=["question_rag_chunk_strategy"],
        success_criteria=["覆盖指标", "说明失败恢复"],
    )


def _weakness() -> WeaknessTracker:
    return WeaknessTracker(
        weakness_id="weakness_rag_depth",
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report_alpha",
        evidence_refs=["application_alpha", "fit_stargazer_backend"],
        created_at=_now(),
        updated_at=_now(),
        title="RAG 深度表达不足",
        description="二面可能追问 RAG 检索评估、chunk 策略和失败恢复。",
        weakness_type=WeaknessType.SKILL_GAP,
        severity=WeaknessSeverity.HIGH,
        state=WeaknessState.OPEN,
        skill_tags=["RAG"],
        target_application_ids=["application_alpha"],
        source_report_ids=["fit_stargazer_backend", "artifact_fit_report_alpha"],
        related_task_ids=["learning_task_rag_eval"],
    )
