"""Low-cost quality evaluation for M11 rule-based retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.retrieval.models import RetrievalQuery, validate_source_type
from tests.test_retrieval_service import _seed_stores, _service

__all__ = []


@dataclass(frozen=True, slots=True)
class RetrievalEvalCase:
    name: str
    query: str
    source_types: list[str]
    expected_source_types: set[str]
    related_application_id: str | None = None
    min_hits: int = 1


def test_m11_retrieval_quality_eval_covers_core_user_paths(tmp_path: Path) -> None:
    stores = _seed_stores(tmp_path)
    service = _service(stores)
    cases = [
        RetrievalEvalCase(
            name="二面准备",
            query="根据我之前星河智能岗位准备二面，重点看 RAG 和 Agent Runtime",
            source_types=[
                "career_application",
                "job_fit_report",
                "note",
                "learning_task",
                "weakness_tracker",
                "external_resource",
                "interview_question",
            ],
            expected_source_types={
                "career_application",
                "job_fit_report",
                "note",
                "learning_task",
                "weakness_tracker",
                "external_resource",
                "interview_question",
            },
            min_hits=7,
        ),
        RetrievalEvalCase(
            name="学习安排",
            query="星河智能二面今天该学什么，RAG 学习任务和能力短板还有哪些没补",
            source_types=[
                "learning_plan",
                "learning_task",
                "weakness_tracker",
                "external_resource",
                "interview_question",
            ],
            related_application_id="application_alpha",
            expected_source_types={
                "learning_plan",
                "learning_task",
                "weakness_tracker",
                "external_resource",
                "interview_question",
            },
            min_hits=5,
        ),
        RetrievalEvalCase(
            name="复盘短板",
            query="我上次 RAG 没答好的地方和二面复盘里记录的短板",
            source_types=["note", "job_fit_report", "weakness_tracker", "learning_task"],
            related_application_id="application_alpha",
            expected_source_types={"note", "job_fit_report", "weakness_tracker"},
            min_hits=3,
        ),
        RetrievalEvalCase(
            name="简历与岗位匹配",
            query="张明 Python FastAPI RAG AI Agent 后端 星河智能 JD 匹配",
            source_types=[
                "resume_profile",
                "career_profile",
                "jd_analysis",
                "job_fit_report",
                "career_application",
            ],
            expected_source_types={
                "resume_profile",
                "career_profile",
                "jd_analysis",
                "job_fit_report",
                "career_application",
            },
            min_hits=5,
        ),
        RetrievalEvalCase(
            name="当前会话文件",
            query="当前会话 JD 里 RAG 检索评估 chunk 策略和异步任务",
            source_types=["session_artifact"],
            expected_source_types={"session_artifact"},
            min_hits=1,
        ),
    ]

    for case in cases:
        pack = service.build_context_pack(
            RetrievalQuery(
                query=case.query,
                session_id="sess_alpha",
                source_types=case.source_types,
                related_application_id=case.related_application_id,
                top_k=20,
                max_chars=12000,
            )
        )
        actual = {validate_source_type(hit.source.source_type).value for hit in pack.hits}

        assert len(pack.hits) >= case.min_hits, case.name
        assert case.expected_source_types <= actual, case.name
        assert len(pack.citations) == len(pack.hits), case.name
        assert all(citation.source_id for citation in pack.citations), case.name
        assert all(hit.match_reason for hit in pack.hits), case.name
