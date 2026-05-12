"""Tests for external career knowledge HTTP endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_knowledge_store
from app.knowledge.models import (
    CompanyProfile,
    ExternalResource,
    InterviewQuestion,
    KnowledgeRecordStatus,
)
from app.knowledge.store import KnowledgeStore
from app.main import app

__all__ = []


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def test_knowledge_api_creates_lists_and_reads_records(tmp_path: Path) -> None:
    store = KnowledgeStore(root_dir=tmp_path / "knowledge", clock=_TickingClock())
    _override_knowledge_store(store)

    try:
        with TestClient(app) as client:
            resource_resp = client.post(
                "/api/knowledge/resources",
                json={
                    "resource_id": "resource_stargazer_interview",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_resource_raw",
                    "evidence_refs": ["artifact_resource_raw", "application_alpha"],
                    "title": "星河智能 AI Agent 后端面经",
                    "resource_type": "pasted_text",
                    "url": "https://example.com/interview",
                    "provider": "用户粘贴",
                    "company": "星河智能",
                    "position": "AI Agent 后端工程师",
                    "target_roles": ["AI 应用后端工程师"],
                    "skill_tags": ["Python", "RAG"],
                    "summary": "面试重点集中在 RAG 和异步任务。",
                    "key_points": ["RAG 深度追问", "Celery 和 Redis 队列"],
                    "raw_artifact_id": "artifact_resource_raw",
                    "related_application_ids": ["application_alpha"],
                    "related_note_ids": ["note_alpha"],
                },
            )
            assert resource_resp.status_code == 200
            resource = _data(resource_resp)
            assert resource["resource_id"] == "resource_stargazer_interview"
            assert resource["resource_type"] == "pasted_text"
            assert resource["created_at"] == "2026-05-12T08:01:00+08:00"

            experience_resp = client.post(
                "/api/knowledge/experiences",
                json={
                    "experience_id": "experience_stargazer_rounds",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_resource_raw",
                    "evidence_refs": ["resource_stargazer_interview"],
                    "source_resource_id": "resource_stargazer_interview",
                    "company": "星河智能",
                    "position": "AI Agent 后端工程师",
                    "seniority": "初级",
                    "interview_rounds": [{"round": "一面", "focus": "项目深挖"}],
                    "interview_process": ["技术一面", "技术二面"],
                    "questions": ["介绍 RAG 项目"],
                    "outcome": "未知",
                    "difficulty": "medium",
                    "summary": "项目深挖较多。",
                    "tags": ["面经", "后端"],
                    "related_application_ids": ["application_alpha"],
                    "related_note_ids": ["note_alpha"],
                },
            )
            assert experience_resp.status_code == 200
            assert _data(experience_resp)["interview_rounds"][0]["round"] == "一面"

            question_resp = client.post(
                "/api/knowledge/questions",
                json={
                    "question_id": "question_rag_chunk_strategy",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_resource_raw",
                    "evidence_refs": ["resource_stargazer_interview", "experience_stargazer_rounds"],
                    "question_text": "RAG 的 chunk 策略如何设计？",
                    "question_type": "technical",
                    "difficulty": "hard",
                    "skill_tags": ["RAG", "向量检索"],
                    "company": "星河智能",
                    "position": "AI Agent 后端工程师",
                    "source_resource_id": "resource_stargazer_interview",
                    "source_experience_id": "experience_stargazer_rounds",
                    "answer_outline": "先讲切分粒度，再讲评估。",
                    "evaluation_points": ["chunk 粒度", "召回率"],
                    "common_pitfalls": ["只讲概念"],
                    "related_application_ids": ["application_alpha"],
                    "related_note_ids": ["note_alpha"],
                },
            )
            assert question_resp.status_code == 200
            assert _data(question_resp)["question_type"] == "technical"

            company_resp = client.post(
                "/api/knowledge/companies",
                json={
                    "company_id": "company_stargazer",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_company_raw",
                    "evidence_refs": ["resource_stargazer_interview"],
                    "company_name": "星河智能",
                    "aliases": ["星河"],
                    "industries": ["AI 应用"],
                    "target_roles": ["AI Agent 后端工程师"],
                    "hiring_signals": ["项目深挖"],
                    "interview_style": "偏项目深挖和系统设计",
                    "common_questions": ["RAG 评估"],
                    "resource_ids": ["resource_stargazer_interview"],
                    "question_ids": ["question_rag_chunk_strategy"],
                    "summary": "关注 AI 应用工程化。",
                },
            )
            assert company_resp.status_code == 200
            assert _data(company_resp)["company_name"] == "星河智能"

            skill_resp = client.post(
                "/api/knowledge/skill-requirements",
                json={
                    "skill_requirement_id": "skill_req_rag_engineering",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_resource_raw",
                    "evidence_refs": ["resource_stargazer_interview"],
                    "skill_name": "RAG 工程化",
                    "category": "rag",
                    "level": "working",
                    "description": "能解释检索、切分、评估和线上稳定性。",
                    "assessment_points": ["chunk 策略", "召回评估"],
                    "role_tags": ["AI 应用后端工程师"],
                    "company_ids": ["company_stargazer"],
                    "resource_ids": ["resource_stargazer_interview"],
                    "question_ids": ["question_rag_chunk_strategy"],
                },
            )
            assert skill_resp.status_code == 200
            assert _data(skill_resp)["category"] == "rag"

            assert [item["resource_id"] for item in _data(client.get("/api/knowledge/resources"))] == [
                "resource_stargazer_interview"
            ]
            assert [item["experience_id"] for item in _data(client.get("/api/knowledge/experiences"))] == [
                "experience_stargazer_rounds"
            ]
            assert [item["question_id"] for item in _data(client.get("/api/knowledge/questions"))] == [
                "question_rag_chunk_strategy"
            ]
            assert [item["company_id"] for item in _data(client.get("/api/knowledge/companies"))] == [
                "company_stargazer"
            ]
            assert [item["skill_requirement_id"] for item in _data(client.get("/api/knowledge/skill-requirements"))] == [
                "skill_req_rag_engineering"
            ]

            assert _data(client.get("/api/knowledge/resources/resource_stargazer_interview"))["title"].startswith(
                "星河智能"
            )
            assert _data(client.get("/api/knowledge/experiences/experience_stargazer_rounds"))["difficulty"] == "medium"
            assert _data(client.get("/api/knowledge/questions/question_rag_chunk_strategy"))["difficulty"] == "hard"
            assert _data(client.get("/api/knowledge/companies/company_stargazer"))["aliases"] == ["星河"]
            assert (
                _data(client.get("/api/knowledge/skill-requirements/skill_req_rag_engineering"))["level"] == "working"
            )

            for response in (
                resource_resp,
                experience_resp,
                question_resp,
                company_resp,
                skill_resp,
            ):
                _assert_no_internal_path_leak(response.json(), tmp_path)
    finally:
        app.dependency_overrides.clear()


def test_knowledge_api_updates_filters_and_archives_records(tmp_path: Path) -> None:
    store = KnowledgeStore(root_dir=tmp_path / "knowledge", clock=_TickingClock())
    store.save_external_resource(_resource("resource_alpha", related_application_id="application_alpha"))
    store.save_external_resource(_resource("resource_beta", related_application_id="application_beta"))
    store.save_interview_question(_question())
    store.save_company_profile(_company())
    _override_knowledge_store(store)

    try:
        with TestClient(app) as client:
            filtered_resources = client.get(
                "/api/knowledge/resources",
                params={"related_application_id": "application_beta"},
            )
            assert filtered_resources.status_code == 200
            assert [item["resource_id"] for item in _data(filtered_resources)] == ["resource_beta"]

            filtered_questions = client.get(
                "/api/knowledge/questions",
                params={"source_resource_id": "resource_alpha"},
            )
            assert filtered_questions.status_code == 200
            assert [item["question_id"] for item in _data(filtered_questions)] == ["question_alpha"]

            update_resource_resp = client.patch(
                "/api/knowledge/resources/resource_alpha",
                json={"summary": "更新后的资料摘要", "url": None, "resource_type": "article"},
            )
            assert update_resource_resp.status_code == 200
            updated_resource = _data(update_resource_resp)
            assert updated_resource["summary"] == "更新后的资料摘要"
            assert updated_resource["url"] is None
            assert updated_resource["resource_type"] == "article"

            update_company_resp = client.patch(
                "/api/knowledge/companies/company_stargazer",
                json={"interview_style": "系统设计偏多"},
            )
            assert update_company_resp.status_code == 200
            assert _data(update_company_resp)["interview_style"] == "系统设计偏多"

            archive_resp = client.post("/api/knowledge/resources/resource_alpha/archive")
            assert archive_resp.status_code == 200
            assert _data(archive_resp)["status"] == "archived"

            hidden_resp = client.get("/api/knowledge/resources/resource_alpha")
            assert hidden_resp.status_code == 404

            visible_resp = client.get(
                "/api/knowledge/resources/resource_alpha",
                params={"include_archived": True},
            )
            assert visible_resp.status_code == 200
            assert _data(visible_resp)["status"] == "archived"
    finally:
        app.dependency_overrides.clear()


def test_knowledge_api_returns_404_for_missing_records(tmp_path: Path) -> None:
    store = KnowledgeStore(root_dir=tmp_path / "knowledge")
    _override_knowledge_store(store)

    try:
        with TestClient(app) as client:
            for path in (
                "/api/knowledge/resources/resource_missing",
                "/api/knowledge/experiences/experience_missing",
                "/api/knowledge/questions/question_missing",
                "/api/knowledge/companies/company_missing",
                "/api/knowledge/skill-requirements/skill_req_missing",
            ):
                response = client.get(path)
                assert response.status_code == 404
                payload = response.json()
                assert payload["code"] == 404
                assert payload["data"] is None
    finally:
        app.dependency_overrides.clear()


def test_knowledge_api_rejects_empty_and_invalid_updates(tmp_path: Path) -> None:
    store = KnowledgeStore(root_dir=tmp_path / "knowledge")
    store.save_external_resource(_resource("resource_alpha", related_application_id="application_alpha"))
    _override_knowledge_store(store)

    try:
        with TestClient(app) as client:
            empty_update_resp = client.patch("/api/knowledge/resources/resource_alpha", json={})
            assert empty_update_resp.status_code == 400
            assert "at least one editable field" in empty_update_resp.json()["msg"]

            invalid_update_resp = client.patch(
                "/api/knowledge/resources/resource_alpha",
                json={"resource_type": "crawler_snapshot"},
            )
            assert invalid_update_resp.status_code == 400

            invalid_query_resp = client.get(
                "/api/knowledge/resources",
                params={"related_application_id": "bad"},
            )
            assert invalid_query_resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def _resource(record_id: str, *, related_application_id: str) -> ExternalResource:
    return ExternalResource(
        resource_id=record_id,
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["artifact_resource_raw", related_application_id],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title=f"{record_id} 面经",
        resource_type="pasted_text",
        company="星河智能",
        position="AI Agent 后端工程师",
        related_application_ids=[related_application_id],
    )


def _question() -> InterviewQuestion:
    return InterviewQuestion(
        question_id="question_alpha",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_resource_raw",
        evidence_refs=["resource_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        question_text="RAG 的 chunk 策略如何设计？",
        question_type="technical",
        source_resource_id="resource_alpha",
    )


def _company() -> CompanyProfile:
    return CompanyProfile(
        company_id="company_stargazer",
        status=KnowledgeRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_company_raw",
        evidence_refs=["resource_alpha"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company_name="星河智能",
        resource_ids=["resource_alpha"],
        question_ids=["question_alpha"],
    )


def _seed_time() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _override_knowledge_store(store: KnowledgeStore) -> None:
    app.dependency_overrides[get_knowledge_store] = lambda: store


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _assert_no_internal_path_leak(payload: Any, tmp_path: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "data/knowledge" not in serialized
    _assert_no_path_key(payload)


def _assert_no_path_key(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"path", "root_dir", "workspace_path"}
            _assert_no_path_key(item)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_path_key(item)
