"""Tests for learning plan HTTP endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.api.deps import get_career_product_store, get_learning_store, get_model_client
from app.career.models import CareerApplication, CareerRecordStatus
from app.career.store import CareerProductStore
from app.domain.protocols import ModelResponse
from app.learning.models import LearningPlan, LearningRecordStatus, LearningTask, WeaknessTracker
from app.learning.store import LearningStore
from app.main import app

__all__ = []


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 5, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        self._current += timedelta(minutes=1)
        return self._current


def test_learning_api_creates_lists_and_reads_records(tmp_path: Path) -> None:
    store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    _override_learning_store(store)

    try:
        with TestClient(app) as client:
            plan_resp = client.post(
                "/api/learning-admin/plans",
                json={
                    "learning_plan_id": "learning_plan_stargazer_backend",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_fit_report",
                    "evidence_refs": ["artifact_fit_report", "fit_stargazer_backend", "application_alpha"],
                    "title": "星河智能面试准备计划",
                    "description": "围绕匹配报告补齐 RAG 和异步任务短板。",
                    "plan_type": "interview_prep",
                    "target_application_id": "application_alpha",
                    "target_role": "AI Agent 后端工程师",
                    "target_company": "星河智能",
                    "start_date": "2026-05-12T00:00:00Z",
                    "end_date": "2026-05-26T00:00:00Z",
                    "priority": "high",
                    "goals": ["讲清楚 RAG 评估", "准备异步任务架构"],
                    "focus_skill_tags": ["RAG", "FastAPI"],
                    "task_ids": ["learning_task_rag_eval"],
                    "weakness_ids": ["weakness_rag_depth"],
                    "review_schedule_ids": ["review_rag_eval"],
                    "progress_summary": "未开始",
                },
            )
            assert plan_resp.status_code == 200
            plan = _data(plan_resp)
            assert plan["learning_plan_id"] == "learning_plan_stargazer_backend"
            assert plan["plan_type"] == "interview_prep"
            assert plan["created_at"] == "2026-05-12T08:01:00+08:00"

            task_resp = client.post(
                "/api/learning-admin/tasks",
                json={
                    "learning_task_id": "learning_task_rag_eval",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_fit_report",
                    "evidence_refs": ["learning_plan_stargazer_backend", "resource_rag_eval"],
                    "title": "准备 RAG 评估回答",
                    "learning_plan_id": "learning_plan_stargazer_backend",
                    "task_type": "write_answer",
                    "priority": "high",
                    "state": "todo",
                    "skill_tags": ["RAG"],
                    "estimated_minutes": 45,
                    "resource_refs": ["resource_rag_eval", "skill_req_rag_engineering"],
                    "question_refs": ["question_rag_chunk_strategy"],
                    "note_refs": ["note_rag_draft"],
                    "success_criteria": ["覆盖指标", "说明失败恢复"],
                },
            )
            assert task_resp.status_code == 200
            task = _data(task_resp)
            assert task["learning_task_id"] == "learning_task_rag_eval"
            assert task["resource_refs"] == ["resource_rag_eval", "skill_req_rag_engineering"]

            checkin_resp = client.post(
                "/api/learning-admin/checkins",
                json={
                    "checkin_id": "checkin_rag_eval_day1",
                    "source_session_id": "sess_alpha",
                    "evidence_refs": ["learning_task_rag_eval", "note_rag_draft"],
                    "learning_plan_id": "learning_plan_stargazer_backend",
                    "learning_task_id": "learning_task_rag_eval",
                    "checkin_date": "2026-05-12T02:00:00Z",
                    "minutes_spent": 30,
                    "progress_state": "in_progress",
                    "summary": "完成 RAG 指标提纲。",
                    "blockers": ["缺少生产案例"],
                    "confidence": "medium",
                    "next_action": "补一个线上评估例子。",
                    "note_refs": ["note_rag_draft"],
                },
            )
            assert checkin_resp.status_code == 200
            assert _data(checkin_resp)["minutes_spent"] == 30

            weakness_resp = client.post(
                "/api/learning-admin/weaknesses",
                json={
                    "weakness_id": "weakness_rag_depth",
                    "source_session_id": "sess_alpha",
                    "source_artifact_id": "artifact_fit_report",
                    "evidence_refs": ["fit_stargazer_backend", "learning_plan_stargazer_backend"],
                    "title": "RAG 深度不足",
                    "description": "匹配报告指出缺少 RAG 生产证据。",
                    "weakness_type": "skill_gap",
                    "severity": "high",
                    "state": "open",
                    "skill_tags": ["RAG"],
                    "target_application_ids": ["application_alpha"],
                    "source_report_ids": ["fit_stargazer_backend", "artifact_fit_report"],
                    "related_task_ids": ["learning_task_rag_eval"],
                    "related_note_ids": ["note_rag_draft"],
                    "last_observed_at": "2026-05-12T00:00:00Z",
                },
            )
            assert weakness_resp.status_code == 200
            assert _data(weakness_resp)["weakness_type"] == "skill_gap"

            review_resp = client.post(
                "/api/learning-admin/reviews",
                json={
                    "review_schedule_id": "review_rag_eval",
                    "source_session_id": "sess_alpha",
                    "evidence_refs": ["learning_task_rag_eval", "weakness_rag_depth"],
                    "title": "复盘 RAG 回答",
                    "learning_plan_id": "learning_plan_stargazer_backend",
                    "learning_task_id": "learning_task_rag_eval",
                    "weakness_id": "weakness_rag_depth",
                    "review_type": "interview_rehearsal",
                    "review_at": "2026-05-14T00:00:00Z",
                    "interval_days": 2,
                    "state": "scheduled",
                    "resource_refs": ["resource_rag_eval"],
                    "question_refs": ["question_rag_chunk_strategy"],
                    "note_refs": ["note_rag_draft"],
                    "next_review_at": "2026-05-16T00:00:00Z",
                    "summary": "口头演练。",
                },
            )
            assert review_resp.status_code == 200
            assert _data(review_resp)["review_type"] == "interview_rehearsal"

            assert [item["learning_plan_id"] for item in _data(client.get("/api/learning/plans"))] == [
                "learning_plan_stargazer_backend"
            ]
            assert [item["learning_task_id"] for item in _data(client.get("/api/learning/tasks"))] == [
                "learning_task_rag_eval"
            ]
            assert [item["checkin_id"] for item in _data(client.get("/api/learning/checkins"))] == [
                "checkin_rag_eval_day1"
            ]
            assert [item["weakness_id"] for item in _data(client.get("/api/learning/weaknesses"))] == [
                "weakness_rag_depth"
            ]
            assert [item["review_schedule_id"] for item in _data(client.get("/api/learning/reviews"))] == [
                "review_rag_eval"
            ]

            assert _data(client.get("/api/learning/plans/learning_plan_stargazer_backend"))["priority"] == "high"
            assert _data(client.get("/api/learning/tasks/learning_task_rag_eval"))["task_type"] == "write_answer"
            assert _data(client.get("/api/learning/checkins/checkin_rag_eval_day1"))["confidence"] == "medium"
            assert _data(client.get("/api/learning/weaknesses/weakness_rag_depth"))["severity"] == "high"
            assert _data(client.get("/api/learning/reviews/review_rag_eval"))["state"] == "scheduled"

            for response in (plan_resp, task_resp, checkin_resp, weakness_resp, review_resp):
                _assert_no_internal_path_leak(response.json(), tmp_path)
    finally:
        app.dependency_overrides.clear()


def test_learning_api_updates_filters_state_and_archives_records(tmp_path: Path) -> None:
    store = LearningStore(root_dir=tmp_path / "learning", clock=_TickingClock())
    store.save_learning_plan(_plan("learning_plan_alpha", target_application_id="application_alpha"))
    store.save_learning_plan(_plan("learning_plan_beta", target_application_id="application_beta"))
    store.save_learning_task(_task("learning_task_alpha", learning_plan_id="learning_plan_alpha"))
    store.save_learning_task(_task("learning_task_beta", learning_plan_id="learning_plan_beta"))
    store.save_weakness_tracker(_weakness("weakness_alpha", target_application_id="application_alpha"))
    store.save_weakness_tracker(_weakness("weakness_beta", target_application_id="application_beta"))
    _override_learning_store(store)

    try:
        with TestClient(app) as client:
            filtered_plans = client.get(
                "/api/learning/plans",
                params={"target_application_id": "application_beta"},
            )
            assert filtered_plans.status_code == 200
            assert [item["learning_plan_id"] for item in _data(filtered_plans)] == ["learning_plan_beta"]

            filtered_tasks = client.get(
                "/api/learning/tasks",
                params={"learning_plan_id": "learning_plan_alpha"},
            )
            assert filtered_tasks.status_code == 200
            assert [item["learning_task_id"] for item in _data(filtered_tasks)] == ["learning_task_alpha"]

            update_plan_resp = client.patch(
                "/api/learning-admin/plans/learning_plan_alpha",
                json={"progress_summary": "已经完成第一轮准备", "priority": "medium"},
            )
            assert update_plan_resp.status_code == 200
            assert _data(update_plan_resp)["progress_summary"] == "已经完成第一轮准备"

            update_task_resp = client.patch(
                "/api/learning-admin/tasks/learning_task_alpha",
                json={"estimated_minutes": 60, "state": "doing"},
            )
            assert update_task_resp.status_code == 200
            assert _data(update_task_resp)["state"] == "doing"

            state_resp = client.post(
                "/api/learning-admin/tasks/learning_task_alpha/state",
                json={"state": "done"},
            )
            assert state_resp.status_code == 200
            completed_task = _data(state_resp)
            assert completed_task["state"] == "done"
            assert completed_task["completed_at"] is not None

            archive_resp = client.post("/api/learning-admin/plans/learning_plan_alpha/archive")
            assert archive_resp.status_code == 200
            assert _data(archive_resp)["status"] == "archived"

            hidden_resp = client.get("/api/learning/plans/learning_plan_alpha")
            assert hidden_resp.status_code == 404

            visible_resp = client.get(
                "/api/learning/plans/learning_plan_alpha",
                params={"include_archived": True},
            )
            assert visible_resp.status_code == 200
            assert _data(visible_resp)["status"] == "archived"

            filtered_weaknesses = client.get(
                "/api/learning/weaknesses",
                params={"target_application_id": "application_beta"},
            )
            assert filtered_weaknesses.status_code == 200
            assert [item["weakness_id"] for item in _data(filtered_weaknesses)] == ["weakness_beta"]
    finally:
        app.dependency_overrides.clear()


def test_learning_api_returns_404_for_missing_records(tmp_path: Path) -> None:
    store = LearningStore(root_dir=tmp_path / "learning")
    _override_learning_store(store)

    try:
        with TestClient(app) as client:
            for path in (
                "/api/learning/plans/learning_plan_missing",
                "/api/learning/tasks/learning_task_missing",
                "/api/learning/checkins/checkin_missing",
                "/api/learning/weaknesses/weakness_missing",
                "/api/learning/reviews/review_missing",
            ):
                response = client.get(path)
                assert response.status_code == 404
                payload = response.json()
                assert payload["code"] == 404
                assert payload["data"] is None
    finally:
        app.dependency_overrides.clear()


def test_learning_api_rejects_empty_and_invalid_updates(tmp_path: Path) -> None:
    store = LearningStore(root_dir=tmp_path / "learning")
    store.save_learning_plan(_plan("learning_plan_alpha", target_application_id="application_alpha"))
    store.save_learning_task(_task("learning_task_alpha", learning_plan_id="learning_plan_alpha"))
    _override_learning_store(store)

    try:
        with TestClient(app) as client:
            empty_update_resp = client.patch("/api/learning-admin/plans/learning_plan_alpha", json={})
            assert empty_update_resp.status_code == 400
            assert "at least one editable field" in empty_update_resp.json()["msg"]

            invalid_update_resp = client.patch(
                "/api/learning-admin/tasks/learning_task_alpha",
                json={"state": "paused"},
            )
            assert invalid_update_resp.status_code == 400

            invalid_query_resp = client.get("/api/learning/tasks", params={"state": "paused"})
            assert invalid_query_resp.status_code == 400
    finally:
        app.dependency_overrides.clear()


def test_learning_public_api_is_read_only(tmp_path: Path) -> None:
    store = LearningStore(root_dir=tmp_path / "learning")
    store.save_learning_plan(_plan("learning_plan_alpha", target_application_id="application_alpha"))
    _override_learning_store(store)

    try:
        with TestClient(app) as client:
            create_resp = client.post(
                "/api/learning/plans",
                json={
                    "learning_plan_id": "learning_plan_should_not_create",
                    "source_session_id": "sess_alpha",
                    "title": "公共接口不应写入",
                },
            )
            update_resp = client.patch("/api/learning/plans/learning_plan_alpha", json={"title": "不应更新"})
            archive_resp = client.post("/api/learning/plans/learning_plan_alpha/archive")

            assert create_resp.status_code == 405
            assert update_resp.status_code == 405
            assert archive_resp.status_code in {404, 405}
            assert client.get("/api/learning/plans/learning_plan_alpha").status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_learning_api_generates_ai_task_drafts_without_persisting(tmp_path: Path) -> None:
    learning_store = LearningStore(root_dir=tmp_path / "learning")
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    career_store.save_career_application(_application("application_alpha"))
    learning_store.save_learning_plan(_plan("learning_plan_alpha", target_application_id="application_alpha"))
    learning_store.save_learning_task(_task("learning_task_existing", learning_plan_id="learning_plan_alpha"))
    model = _DraftModel(
        {
            "drafts": [
                {
                    "title": "RAG 召回评估实战",
                    "description": "补齐召回指标、失败样例和优化复盘，形成可面试表达的项目证据。",
                    "task_type": "write_answer",
                    "priority": "high",
                    "estimated_minutes": 120,
                    "skill_tags": ["RAG", "召回评估", "重排"],
                    "success_criteria": ["完成评估指标表", "输出一份复盘笔记"],
                    "reason": "匹配报告暴露 RAG 深度不足，需要补齐工程化证据。",
                    "source_refs": ["application_alpha", "invalid_ref"],
                }
            ]
        }
    )
    _override_learning_store(learning_store)
    _override_career_store(career_store)
    _override_model_client(model)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/learning-admin/task-drafts/generate",
                json={"application_id": "application_alpha", "max_drafts": 3},
            )
            assert response.status_code == 200
            data = _data(response)
            assert len(data["drafts"]) == 1
            draft = data["drafts"][0]
            assert draft["title"] == "RAG 召回评估实战"
            assert draft["task_type"] == "write_answer"
            assert draft["priority"] == "high"
            assert draft["estimated_minutes"] == 120
            assert draft["source_refs"] == ["application_alpha"]
            assert [task.learning_task_id for task in learning_store.list_learning_tasks()] == [
                "learning_task_existing"
            ]
            assert model.calls
            assert "application_alpha" in model.calls[0]["messages"][0]["content"]
            assert "learning_task_existing 任务" in model.calls[0]["messages"][0]["content"]
    finally:
        app.dependency_overrides.clear()


def test_learning_api_filters_duplicate_ai_task_drafts(tmp_path: Path) -> None:
    learning_store = LearningStore(root_dir=tmp_path / "learning")
    career_store = CareerProductStore(root_dir=tmp_path / "career")
    career_store.save_career_application(_application("application_alpha"))
    learning_store.save_learning_plan(_plan("learning_plan_alpha", target_application_id="application_alpha"))
    learning_store.save_learning_task(_task("learning_task_existing", learning_plan_id="learning_plan_alpha"))
    model = _DraftModel(
        {
            "drafts": [
                {
                    "title": "learning_task_existing 任务",
                    "description": "重复任务，应该被过滤。",
                    "priority": "high",
                    "estimated_minutes": 60,
                    "source_refs": ["application_alpha"],
                }
            ]
        }
    )
    _override_learning_store(learning_store)
    _override_career_store(career_store)
    _override_model_client(model)

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/learning-admin/task-drafts/generate",
                json={"application_id": "application_alpha", "max_drafts": 3},
            )
            assert response.status_code == 200
            assert _data(response)["drafts"] == []
            assert [task.learning_task_id for task in learning_store.list_learning_tasks()] == [
                "learning_task_existing"
            ]
    finally:
        app.dependency_overrides.clear()


def _plan(record_id: str, *, target_application_id: str) -> LearningPlan:
    return LearningPlan(
        learning_plan_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["artifact_fit_report", target_application_id],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title=f"{record_id} 学习计划",
        plan_type="interview_prep",
        target_application_id=target_application_id,
        priority="high",
        task_ids=[],
        weakness_ids=[],
        review_schedule_ids=[],
    )


def _application(record_id: str) -> CareerApplication:
    return CareerApplication(
        application_id=record_id,
        status=CareerRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_application",
        evidence_refs=["artifact_application"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        company="星河智能",
        position="AI Agent 后端工程师",
        stage="interviewing",
        priority="high",
        summary="候选人需要补齐 RAG 与 Agent 工程化证据。",
        next_actions=["准备 RAG 评估回答", "补充 Agent 状态管理案例"],
        risks=["RAG 生产经验不足"],
    )


def _task(record_id: str, *, learning_plan_id: str) -> LearningTask:
    return LearningTask(
        learning_task_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=[learning_plan_id, "resource_rag_eval"],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title=f"{record_id} 任务",
        learning_plan_id=learning_plan_id,
        task_type="write_answer",
        priority="high",
        state="todo",
        skill_tags=["RAG"],
        resource_refs=["resource_rag_eval"],
    )


def _weakness(record_id: str, *, target_application_id: str) -> WeaknessTracker:
    return WeaknessTracker(
        weakness_id=record_id,
        status=LearningRecordStatus.ACTIVE,
        source_session_id="sess_alpha",
        source_artifact_id="artifact_fit_report",
        evidence_refs=["fit_stargazer_backend", target_application_id],
        created_at=_seed_time(),
        updated_at=_seed_time(),
        title=f"{record_id} 短板",
        weakness_type="skill_gap",
        severity="high",
        state="open",
        target_application_ids=[target_application_id],
        source_report_ids=["fit_stargazer_backend"],
    )


def _seed_time() -> datetime:
    return datetime(2026, 5, 12, 0, 0, tzinfo=UTC)


def _override_learning_store(store: LearningStore) -> None:
    app.dependency_overrides[get_learning_store] = lambda: store


def _override_career_store(store: CareerProductStore) -> None:
    app.dependency_overrides[get_career_product_store] = lambda: store


def _override_model_client(model: "_DraftModel") -> None:
    app.dependency_overrides[get_model_client] = lambda: model


class _DraftModel:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        self.calls.append({"system_prompt": system_prompt, "messages": messages, "tools": tools})
        return ModelResponse(content=json.dumps(self.payload, ensure_ascii=False), tool_calls=[])


def _data(response: Any) -> Any:
    payload = response.json()
    assert payload["code"] == 0
    assert payload["msg"] == "ok"
    return payload["data"]


def _assert_no_internal_path_leak(payload: Any, tmp_path: Path) -> None:
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "data/learning" not in serialized
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
