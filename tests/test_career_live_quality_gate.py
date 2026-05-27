from pathlib import Path

from app.career.models import CareerProfile, CareerRecordStatus, JDAnalysis, JobFitReport, ResumeProfile
from app.career.store import CareerProductStore
from app.core.time import app_now
from app.domain.models import EventRecord, SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from tools.career_live_quality_gate import check_career_live_quality


def test_live_quality_gate_fails_when_final_answer_drifts_from_source_jd(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    _append_assistant_message(
        repository,
        session_id=session_id,
        content="已完成 C++ 游戏服务端开发工程师的匹配分析，重点准备 Linux、MySQL 和网络编程。",
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert not report.success
    assert [item.code for item in report.findings] == ["final_answer_source_drift"]


def test_live_quality_gate_passes_when_answer_matches_source_jd(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    _append_assistant_message(
        repository,
        session_id=session_id,
        content="已完成 AI 应用开发工程师匹配分析，重点准备 Python、FastAPI、RAG 和 Agent 工程经验。",
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert report.success
    assert report.findings == []


def test_live_quality_gate_fails_when_jd_analysis_contains_unsupported_game_role(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path, save_jd=False)
    now = app_now()
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd"],
            created_at=now,
            updated_at=now,
            position="C++ 游戏服务端开发工程师",
            required_skills=["C++", "Linux", "MySQL"],
        )
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert not report.success
    assert [item.code for item in report.findings] == ["jd_analysis_source_drift"]


def test_live_quality_gate_fails_when_career_profile_drifts_from_resume_source(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    now = app_now()
    store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=["resume_profile_quality", "artifact_resume"],
            created_at=now,
            updated_at=now,
            education_summary="硕士在读，西北农林科技大学生物学，预计2026年6月毕业。",
            skills=["R语言与RNA-seq分析"],
        )
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert not report.success
    assert "career_profile_source_drift" in [item.code for item in report.findings]


def test_live_quality_gate_allows_diagnostic_missing_school_issue(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    now = app_now()
    store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_default",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=now,
            updated_at=now,
            skills=["Python", "FastAPI"],
            resume_issues=["缺少教育背景学校和时间"],
        )
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert report.success


def test_live_quality_gate_allows_vector_search_as_jd_gap(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path, save_fit=False)
    now = app_now()
    store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd",
            evidence_refs=["resume_profile_quality", "jd_quality", "artifact_jd"],
            created_at=now,
            updated_at=now,
            jd_analysis_id="jd_quality",
            resume_profile_id="resume_profile_quality",
            career_profile_id="career_profile_quality",
            matched_evidence=["Python/FastAPI 后端经验"],
            gaps=["向量检索经验需要更强表达"],
            interview_preparation_focus=["RAG 召回评估", "向量检索原理"],
        )
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert report.success


def test_live_quality_gate_reads_future_agent_outputs(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    _append_assistant_message(
        repository,
        session_id=session_id,
        content="research summary: 目标是 C++ 游戏服务端开发工程师。",
        agent_id="research_agent",
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert not report.success
    assert report.findings[0].reference == "evt_research_agent_answer"


def test_live_quality_gate_does_not_treat_generated_artifact_as_source(tmp_path: Path) -> None:
    repository, store, session_id = _base_stack(tmp_path)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_generated_report",
        kind="generated_file",
        content="错误报告：目标岗位是 C++ 游戏服务端开发工程师。",
    )
    _append_assistant_message(
        repository,
        session_id=session_id,
        content="已完成 C++ 游戏服务端开发工程师的匹配分析。",
    )

    report = check_career_live_quality(repository=repository, career_store=store, session_id=session_id)

    assert not report.success
    assert {item.code for item in report.findings} == {
        "final_answer_source_drift",
        "generated_artifact_source_drift",
    }


def _base_stack(
    tmp_path: Path,
    *,
    save_jd: bool = True,
    save_fit: bool = True,
) -> tuple[JsonlSessionRepository, CareerProductStore, str]:
    session_id = "sess_live_quality_gate"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume",
        kind="uploaded_file",
        content="候选人：张三\n技能：Python、FastAPI、RAG、Agent Runtime。\n",
    )
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_jd",
        kind="pasted_text",
        content="公司招聘 AI 应用开发工程师，要求 Python、FastAPI、RAG、Agent 工程经验，熟悉向量检索。",
    )
    store = CareerProductStore(root_dir=tmp_path / "career", clock=app_now)
    now = app_now()
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume"],
            created_at=now,
            updated_at=now,
            skills=["Python", "FastAPI", "RAG", "Agent Runtime"],
        )
    )
    if save_jd:
        store.save_jd_analysis(
            JDAnalysis(
                jd_analysis_id="jd_quality",
                status=CareerRecordStatus.ACTIVE,
                source_session_id=session_id,
                source_artifact_id="artifact_jd",
                evidence_refs=["artifact_jd"],
                created_at=now,
                updated_at=now,
                position="AI 应用开发工程师",
                required_skills=["Python", "FastAPI", "RAG", "Agent 工程"],
                keywords=["向量检索"],
            )
        )
    if save_fit:
        store.save_job_fit_report(
            JobFitReport(
                job_fit_report_id="fit_quality",
                status=CareerRecordStatus.ACTIVE,
                source_session_id=session_id,
                source_artifact_id="artifact_jd",
                evidence_refs=["resume_profile_quality", "jd_quality", "artifact_jd"],
                created_at=now,
                updated_at=now,
                jd_analysis_id="jd_quality",
                resume_profile_id="resume_profile_quality",
                career_profile_id="career_profile_quality",
                matched_evidence=["Python/FastAPI 后端经验"],
                gaps=["RAG 评估指标表达需要加强"],
            )
        )
    return repository, store, session_id


def _add_artifact(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    artifact_id: str,
    kind: str,
    content: str,
) -> None:
    root = repository.get_session_root_path(session_id)
    artifact_dir = root / "artifacts" / artifact_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    content_path = artifact_dir / "content.txt"
    content_path.write_text(content, encoding="utf-8")
    now = app_now()
    repository.add_or_update_session_artifact(
        SessionArtifact(
            artifact_id=artifact_id,
            session_id=session_id,
            kind=kind,
            title=f"{artifact_id}.txt",
            media_type="text/plain",
            size_bytes=content_path.stat().st_size,
            status="ready",
            visibility="session_shared",
            created_at=now,
            updated_at=now,
            storage_relpath=str(content_path.relative_to(root)),
            text_relpath=str(content_path.relative_to(root)),
            text_char_count=len(content),
            token_estimate=4,
            parsed_at=now,
        )
    )


def _append_assistant_message(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    content: str,
    agent_id: str = "agent_main",
) -> None:
    repository.append_agent_event(
        session_id,
        agent_id,
        EventRecord(
            event_id=f"evt_{agent_id}_answer",
            session_id=session_id,
            type="assistant_message",
            payload={"content": content},
            created_at=app_now(),
            agent_id=agent_id,
            run_id="run_test",
        ),
    )
