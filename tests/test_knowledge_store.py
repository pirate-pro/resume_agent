"""Tests for the external career knowledge store."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from app.core.errors import StorageError, ValidationError
from app.knowledge.models import (
    CompanyProfile,
    ExperiencePost,
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


def _now() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _store(tmp_path: Path) -> KnowledgeStore:
    return KnowledgeStore(root_dir=tmp_path / "knowledge")


def _resource(record_id: str = "resource_stargazer_interview") -> ExternalResource:
    return ExternalResource(
        resource_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["artifact_resource_raw", "sess_alpha", "application_alpha"],
        created_at=_now(),
        updated_at=_now(),
        title="星河智能 AI Agent 后端面经",
        resource_type=ResourceType.PASTED_TEXT,
        url="https://example.com/interview",
        provider="用户粘贴",
        company="星河智能",
        position="AI Agent 后端工程师",
        target_roles=["AI 应用后端工程师", "Agent 平台工程师"],
        skill_tags=["Python", "RAG", "系统设计"],
        summary="面试重点集中在 RAG、异步任务和多 Agent 架构。",
        key_points=["RAG 深度追问", "Celery 和 Redis 队列", "Agent 工程化"],
        raw_artifact_id="artifact_resource_raw",
        related_application_ids=["application_alpha"],
        related_note_ids=["note_alpha"],
    )


def _experience(record_id: str = "experience_stargazer_rounds") -> ExperiencePost:
    return ExperiencePost(
        experience_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["resource_stargazer_interview", "artifact_resource_raw"],
        created_at=_now(),
        updated_at=_now(),
        source_resource_id="resource_stargazer_interview",
        company="星河智能",
        position="AI Agent 后端工程师",
        seniority="初级",
        interview_rounds=[
            {"round": "一面", "focus": "项目深挖"},
            {"round": "二面", "focus": "系统设计"},
        ],
        interview_process=["HR 电话", "技术一面", "技术二面"],
        questions=["介绍 RAG 项目", "如何设计异步任务审计"],
        outcome="未知",
        difficulty=InterviewDifficulty.MEDIUM,
        summary="项目深挖多，要求能讲清楚工程权衡。",
        tags=["面经", "后端"],
        related_application_ids=["application_alpha"],
        related_note_ids=["note_alpha"],
    )


def _question(record_id: str = "question_rag_chunk_strategy") -> InterviewQuestion:
    return InterviewQuestion(
        question_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["resource_stargazer_interview", "experience_stargazer_rounds"],
        created_at=_now(),
        updated_at=_now(),
        question_text="RAG 的 chunk 策略如何设计，如何评估效果？",
        question_type=QuestionType.TECHNICAL,
        difficulty=InterviewDifficulty.HARD,
        skill_tags=["RAG", "向量检索"],
        company="星河智能",
        position="AI Agent 后端工程师",
        source_resource_id="resource_stargazer_interview",
        source_experience_id="experience_stargazer_rounds",
        answer_outline="先讲切分粒度、召回指标，再讲线上评估和失败恢复。",
        evaluation_points=["chunk 粒度", "召回率", "评估集", "线上观测"],
        common_pitfalls=["只讲概念，不讲指标", "没有失败案例"],
        related_application_ids=["application_alpha"],
        related_note_ids=["note_alpha"],
    )


def _company(record_id: str = "company_stargazer") -> CompanyProfile:
    return CompanyProfile(
        company_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_company_raw",
        evidence_refs=["resource_stargazer_interview", "artifact_company_raw"],
        created_at=_now(),
        updated_at=_now(),
        company_name="星河智能",
        aliases=["星河"],
        industries=["AI 应用", "企业知识库"],
        target_roles=["AI Agent 后端工程师"],
        hiring_signals=["项目深挖", "工程稳定性"],
        interview_style="偏项目深挖和系统设计",
        common_questions=["RAG 评估", "异步任务设计"],
        resource_ids=["resource_stargazer_interview"],
        question_ids=["question_rag_chunk_strategy"],
        summary="关注 AI 应用工程化和后端稳定性。",
    )


def _skill(record_id: str = "skill_req_rag_engineering") -> SkillRequirement:
    return SkillRequirement(
        skill_requirement_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["resource_stargazer_interview", "question_rag_chunk_strategy"],
        created_at=_now(),
        updated_at=_now(),
        skill_name="RAG 工程化",
        category=SkillCategory.RAG,
        level=SkillLevel.WORKING,
        description="能解释检索、切分、评估和线上稳定性。",
        assessment_points=["chunk 策略", "召回评估", "失败恢复"],
        role_tags=["AI 应用后端工程师"],
        company_ids=["company_stargazer"],
        resource_ids=["resource_stargazer_interview"],
        question_ids=["question_rag_chunk_strategy"],
    )


def test_knowledge_store_persists_all_record_types_across_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_external_resource(_resource())
    store.save_experience_post(_experience())
    store.save_interview_question(_question())
    store.save_company_profile(_company())
    store.save_skill_requirement(_skill())

    reloaded = _store(tmp_path)
    resource = reloaded.get_external_resource("resource_stargazer_interview")
    experience = reloaded.get_experience_post("experience_stargazer_rounds")
    question = reloaded.get_interview_question("question_rag_chunk_strategy")
    company = reloaded.get_company_profile("company_stargazer")
    skill = reloaded.get_skill_requirement("skill_req_rag_engineering")

    assert resource is not None
    assert resource.resource_type == ResourceType.PASTED_TEXT
    assert resource.raw_artifact_id == "artifact_resource_raw"
    assert experience is not None
    assert experience.interview_rounds[0]["round"] == "一面"
    assert question is not None
    assert question.question_type == QuestionType.TECHNICAL
    assert company is not None
    assert company.resource_ids == ["resource_stargazer_interview"]
    assert skill is not None
    assert skill.category == SkillCategory.RAG
    assert not list((tmp_path / "knowledge").rglob("*.md"))


def test_knowledge_store_lists_active_records_and_archives(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_external_resource(_resource("resource_active"))
    store.save_external_resource(_resource("resource_archived"))
    store.save_interview_question(_question("question_active"))
    store.save_interview_question(_question("question_archived"))

    archived_resource = store.archive_external_resource("resource_archived")
    archived_question = store.archive_interview_question("question_archived")

    assert archived_resource is not None
    assert archived_resource.status == KnowledgeRecordStatus.ARCHIVED
    assert archived_question is not None
    assert archived_question.status == KnowledgeRecordStatus.ARCHIVED
    assert [record.resource_id for record in store.list_external_resources()] == ["resource_active"]
    assert {record.resource_id for record in store.list_external_resources(include_archived=True)} == {
        "resource_active",
        "resource_archived",
    }
    assert [record.question_id for record in store.list_interview_questions()] == ["question_active"]
    assert store.archive_external_resource("resource_missing") is None
    assert store.archive_interview_question("question_missing") is None


def test_knowledge_store_filters_resource_and_derived_records(tmp_path: Path) -> None:
    store = _store(tmp_path)
    resource = _resource("resource_alpha")
    resource.related_application_ids = ["application_alpha"]
    other = _resource("resource_beta")
    other.related_application_ids = ["application_beta"]
    experience = _experience("experience_alpha")
    experience.source_resource_id = "resource_alpha"
    question = _question("question_alpha")
    question.source_resource_id = "resource_alpha"
    store.save_external_resource(resource)
    store.save_external_resource(other)
    store.save_experience_post(experience)
    store.save_interview_question(question)

    assert [item.resource_id for item in store.list_external_resources(related_application_id="application_beta")] == [
        "resource_beta"
    ]
    assert [item.experience_id for item in store.list_experience_posts(source_resource_id="resource_alpha")] == [
        "experience_alpha"
    ]
    assert [item.question_id for item in store.list_interview_questions(source_resource_id="resource_alpha")] == [
        "question_alpha"
    ]


def test_knowledge_store_owns_timestamps_and_serializes_shanghai_time(tmp_path: Path) -> None:
    ticks = iter(
        [
            datetime(2026, 5, 12, 1, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 2, 0, tzinfo=UTC),
            datetime(2026, 5, 12, 3, 0, tzinfo=UTC),
        ]
    )
    store = KnowledgeStore(root_dir=tmp_path / "knowledge", clock=lambda: next(ticks))

    created = store.save_external_resource(_resource())
    updated = store.update_external_resource("resource_stargazer_interview", updates={"summary": "更新后的摘要"})
    archived = store.archive_external_resource("resource_stargazer_interview")
    payload = json.loads(
        (tmp_path / "knowledge" / "external_resources" / "resource_stargazer_interview.json").read_text(
            encoding="utf-8"
        )
    )

    assert created.created_at.isoformat() == "2026-05-12T09:00:00+08:00"
    assert created.updated_at == created.created_at
    assert updated.created_at == created.created_at
    assert updated.updated_at.isoformat() == "2026-05-12T10:00:00+08:00"
    assert archived is not None
    assert archived.created_at == created.created_at
    assert archived.updated_at.isoformat() == "2026-05-12T11:00:00+08:00"
    assert payload["created_at"] == "2026-05-12T09:00:00+08:00"
    assert payload["updated_at"] == "2026-05-12T11:00:00+08:00"


def test_knowledge_update_validates_allowed_fields(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_external_resource(_resource())
    store.save_experience_post(_experience())
    store.save_interview_question(_question())
    store.save_company_profile(_company())
    store.save_skill_requirement(_skill())

    resource = store.update_external_resource(
        "resource_stargazer_interview",
        updates={"resource_type": "article", "target_roles": ["RAG 平台工程师"], "url": None},
    )
    experience = store.update_experience_post(
        "experience_stargazer_rounds",
        updates={"difficulty": "hard", "interview_process": ["技术面", "HR 面"]},
    )
    question = store.update_interview_question(
        "question_rag_chunk_strategy",
        updates={"question_type": "system_design", "evaluation_points": ["架构权衡"]},
    )
    company = store.update_company_profile("company_stargazer", updates={"interview_style": "系统设计偏多"})
    skill = store.update_skill_requirement("skill_req_rag_engineering", updates={"level": "strong"})

    assert resource.resource_type == ResourceType.ARTICLE
    assert resource.url is None
    assert experience.difficulty == InterviewDifficulty.HARD
    assert question.question_type == QuestionType.SYSTEM_DESIGN
    assert company.interview_style == "系统设计偏多"
    assert skill.level == SkillLevel.STRONG
    with pytest.raises(ValidationError):
        store.update_external_resource("resource_stargazer_interview", updates={"created_at": _now()})
    with pytest.raises(ValidationError):
        store.update_interview_question("question_missing", updates={"question_text": "新题目"})


def test_knowledge_models_validate_ids_status_and_refs_format(tmp_path: Path) -> None:
    store = _store(tmp_path)

    with pytest.raises(ValidationError):
        store.save_external_resource(_resource("bad-resource"))
    with pytest.raises(ValidationError):
        ExternalResource(
            resource_id="resource_alpha",
            status=cast(KnowledgeRecordStatus, "deleted"),
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="坏状态",
            resource_type=ResourceType.LINK,
        )
    with pytest.raises(ValidationError):
        ExternalResource(
            resource_id="resource_alpha",
            status=KnowledgeRecordStatus.ACTIVE,
            source_session_id="session_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            title="坏会话",
            resource_type=ResourceType.LINK,
        )
    with pytest.raises(ValidationError):
        bad_ref = _resource("resource_bad_ref")
        bad_ref.evidence_refs = ["bad_ref"]
        store.save_external_resource(bad_ref)
    with pytest.raises(ValidationError):
        bad_question = _question("question_bad_resource")
        bad_question.source_resource_id = "fit_alpha"
        store.save_interview_question(bad_question)


def test_knowledge_refs_validate_format_but_not_cross_record_existence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    resource = ExternalResource(
        resource_id="resource_orphan",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing",
        evidence_refs=[
            "artifact_missing",
            "application_missing",
            "note_missing",
            "company_missing",
            "skill_req_missing",
        ],
        created_at=_now(),
        updated_at=_now(),
        title="孤立外部资料",
        resource_type=ResourceType.PASTED_TEXT,
        related_application_ids=["application_missing"],
        related_note_ids=["note_missing"],
    )
    question = InterviewQuestion(
        question_id="question_orphan",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_missing",
        evidence_refs=["resource_missing", "experience_missing"],
        created_at=_now(),
        updated_at=_now(),
        question_text="不存在的来源也允许保存吗？",
        question_type=QuestionType.OTHER,
        source_resource_id="resource_missing",
        source_experience_id="experience_missing",
    )

    store.save_external_resource(resource)
    store.save_interview_question(question)

    loaded_resource = store.get_external_resource("resource_orphan")
    loaded_question = store.get_interview_question("question_orphan")
    assert loaded_resource is not None
    assert loaded_resource.source_artifact_id == "artifact_missing"
    assert loaded_question is not None
    assert loaded_question.source_resource_id == "resource_missing"


def test_knowledge_store_raises_stable_error_for_corrupt_json(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_external_resource(_resource("resource_bad"))
    path = tmp_path / "knowledge" / "external_resources" / "resource_bad.json"
    path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_external_resource("resource_bad")
    with pytest.raises(StorageError):
        store.list_external_resources()


def test_knowledge_store_rejects_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_external_resource(_resource("resource_bad_schema"))
    path = tmp_path / "knowledge" / "external_resources" / "resource_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["target_roles"] = "AI 后端"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_external_resource("resource_bad_schema")
    with pytest.raises(StorageError):
        store.list_external_resources()


def test_knowledge_store_rejects_source_session_schema_type_mismatch_on_read(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save_company_profile(_company("company_bad_schema"))
    path = tmp_path / "knowledge" / "company_profiles" / "company_bad_schema.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["source_session_id"] = 123
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StorageError):
        store.get_company_profile("company_bad_schema")
    with pytest.raises(StorageError):
        store.list_company_profiles()


def test_knowledge_store_rejects_nested_json_non_serializable() -> None:
    with pytest.raises(ValidationError):
        ExperiencePost(
            experience_id="experience_bad_rounds",
            status=KnowledgeRecordStatus.ACTIVE,
            source_session_id="sess_alpha",
            source_artifact_id=None,
            evidence_refs=[],
            created_at=_now(),
            updated_at=_now(),
            interview_rounds=[{"bad": object()}],
        )
