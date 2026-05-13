import asyncio
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

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
from app.domain.models import SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.core.time import app_now

from tools.smoke_career_live_flow import (
    FlowReport,
    LiveStack,
    TurnReport,
    infer_failure_stage,
    inspect_flow_outputs,
    print_report,
    run_all,
)


def test_live_smoke_report_prints_concise_failure_summary(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    report = FlowReport(
        run_index=1,
        session_id="sess_live_career_test",
        data_dir=tmp_path / "run_001",
        success=False,
        elapsed_seconds=12.34,
        turns=[
            TurnReport(
                name="JD 匹配分析",
                answer="这是一段很长的模型回答。" * 80,
                elapsed_seconds=8.0,
                tool_calls=["career_jd_analysis_save", "career_job_fit_report_save"],
            )
        ],
        record_ids={
            "resume_profiles": ["resume_profile_test"],
            "career_profiles": ["career_profile_default"],
            "jd_analyses": ["jd_test"],
            "job_fit_reports": [],
            "resume_versions": [],
            "career_applications": [],
        },
        artifact_ids=[f"artifact_{index:03d}" for index in range(12)],
        tool_call_counts={"career_jd_analysis_save": 1, "career_job_fit_report_save": 1},
        errors=[
            "缺少产品记录: job_fit_reports",
            "工具失败: career_job_fit_report_save -> 模拟失败",
        ],
        failed_stage="JD 匹配分析",
        missing_records=["job_fit_reports", "resume_versions"],
        failed_tools=["career_job_fit_report_save"],
        consistency_errors=["error / source_artifact_missing: 缺少 artifact"],
        quality_gate_passed=False,
        quality_error_codes=["source_artifact_missing"],
    )

    print_report([report])

    output = capsys.readouterr().out
    assert "失败摘要:" in output
    assert "失败阶段: JD 匹配分析" in output
    assert "缺失产品记录: [job_fit_reports, resume_versions]" in output
    assert "失败工具: [career_job_fit_report_save]" in output
    assert "质量门禁: 失败 error_codes=[source_artifact_missing]" in output
    assert "质量错误码: [source_artifact_missing]" in output
    assert "record_counts:" in output
    assert "artifact_count: 12" in output
    assert "answer_preview:" in output
    assert len(output) < 3000


def test_infer_failure_stage_from_missing_records(tmp_path: Path) -> None:
    report = FlowReport(
        run_index=1,
        session_id="sess_live_career_test",
        data_dir=tmp_path / "run_001",
        success=False,
        elapsed_seconds=0,
        missing_records=["resume_versions"],
    )

    assert infer_failure_stage(report) == "定制简历版本"


def test_live_smoke_fails_when_checker_rejects_resume_version(tmp_path: Path) -> None:
    session_id = "sess_live_quality"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume",
        content="候选人：张三\n项目：Agent 工具调用。\n",
    )
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_diagnosis", content="诊断报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_jd", content="JD 要求 Python FastAPI RAG")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_report", content="匹配报告")
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume_version",
        content="项目成果：检索命中率 85%+，端到端时延 <2s。",
    )
    store = CareerProductStore(root_dir=tmp_path / "career", clock=app_now)
    _save_product_records(store, session_id=session_id)
    report = FlowReport(
        run_index=1,
        session_id=session_id,
        data_dir=tmp_path,
        success=False,
        elapsed_seconds=0,
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert report.quality_gate_passed is False
    assert report.failed_stage == "产品数据一致性检查"
    assert "resume_version_placeholder_text" in report.quality_error_codes
    assert "resume_version_unverified_metric" in report.quality_error_codes
    assert any("产品数据一致性错误" in error for error in report.errors)


def test_live_smoke_report_fails_when_project_action_does_not_merge(tmp_path: Path) -> None:
    session_id = "sess_live_project_action"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume",
        content="候选人：张三\n项目：Agent 工具调用。\n",
    )
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_diagnosis", content="诊断报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_jd", content="JD 要求 Python FastAPI RAG")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_report", content="匹配报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_resume_version", content="定制简历")
    store = CareerProductStore(root_dir=tmp_path / "career", clock=app_now)
    _save_product_records(store, session_id=session_id)
    report = FlowReport(
        run_index=1,
        session_id=session_id,
        data_dir=tmp_path,
        success=False,
        elapsed_seconds=0,
        turns=[
            TurnReport(
                name="项目动作：投递前检查",
                answer="已完成检查，但没有回写项目。",
                elapsed_seconds=1.0,
                tool_calls=["career_application_get"],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "项目动作未回写 CareerApplication。" in report.errors


def test_live_smoke_passes_project_action_argument_to_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    def fake_run_live_flow(**kwargs: object) -> FlowReport:
        seen.update(kwargs)
        return FlowReport(
            run_index=1,
            session_id="sess_fake",
            data_dir=tmp_path / "run_001",
            success=True,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr("tools.smoke_career_live_flow.Settings.load", lambda: SimpleNamespace())
    monkeypatch.setattr("tools.smoke_career_live_flow.run_live_flow", fake_run_live_flow)
    args = Namespace(
        data_dir=tmp_path,
        concurrency=1,
        runs=1,
        max_tool_rounds=8,
        project_action="checklist",
        retrieval_action="none",
        quiet=True,
    )

    reports = asyncio.run(run_all(args))

    assert reports[0].success is True
    assert seen["project_action"] == "checklist"


def test_live_smoke_passes_retrieval_action_argument_to_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}

    def fake_run_live_flow(**kwargs: object) -> FlowReport:
        seen.update(kwargs)
        return FlowReport(
            run_index=1,
            session_id="sess_fake",
            data_dir=tmp_path / "run_001",
            success=True,
            elapsed_seconds=0.0,
        )

    monkeypatch.setattr("tools.smoke_career_live_flow.Settings.load", lambda: SimpleNamespace())
    monkeypatch.setattr("tools.smoke_career_live_flow.run_live_flow", fake_run_live_flow)
    args = Namespace(
        data_dir=tmp_path,
        concurrency=1,
        runs=1,
        max_tool_rounds=8,
        project_action="none",
        retrieval_action="learning_task",
        quiet=True,
    )

    reports = asyncio.run(run_all(args))

    assert reports[0].success is True
    assert seen["retrieval_action"] == "learning_task"


def test_live_smoke_report_fails_when_m12_action_skips_retrieval(tmp_path: Path) -> None:
    session_id = "sess_live_m12_action"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume",
        content="候选人：张三\n项目：Agent 工具调用。\n",
    )
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_diagnosis", content="诊断报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_jd", content="JD 要求 Python FastAPI RAG")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_report", content="匹配报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_resume_version", content="定制简历")
    store = CareerProductStore(root_dir=tmp_path / "career", clock=app_now)
    _save_product_records(store, session_id=session_id)
    report = FlowReport(
        run_index=1,
        session_id=session_id,
        data_dir=tmp_path,
        success=False,
        elapsed_seconds=0,
        turns=[
            TurnReport(
                name="M12动作：召回创建学习任务",
                answer="已创建学习任务，但没有召回。",
                elapsed_seconds=1.0,
                tool_calls=["learning_task_create"],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M12 动作未先调用 retrieval_search。" in report.errors
    assert "M12 动作未调用 retrieval_context_pack。" in report.errors


def test_live_smoke_report_fails_when_m12_learning_updates_career(tmp_path: Path) -> None:
    session_id = "sess_live_m12_learning"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _add_artifact(
        repository,
        session_id=session_id,
        artifact_id="artifact_resume",
        content="候选人：张三\n项目：Agent 工具调用。\n",
    )
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_diagnosis", content="诊断报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_jd", content="JD 要求 Python FastAPI RAG")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_report", content="匹配报告")
    _add_artifact(repository, session_id=session_id, artifact_id="artifact_resume_version", content="定制简历")
    store = CareerProductStore(root_dir=tmp_path / "career", clock=app_now)
    _save_product_records(store, session_id=session_id)
    report = FlowReport(
        run_index=1,
        session_id=session_id,
        data_dir=tmp_path,
        success=False,
        elapsed_seconds=0,
        turns=[
            TurnReport(
                name="M12动作：召回创建学习任务",
                answer="已创建学习任务，同时错误更新了求职项目。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "learning_task_create",
                    "career_application_merge",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M12 学习安排动作不应更新 CareerApplication。" in report.errors


def _add_artifact(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    artifact_id: str,
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
            kind="generated_file",
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


def _save_product_records(store: CareerProductStore, *, session_id: str) -> None:
    store.save_resume_profile(
        ResumeProfile(
            resume_profile_id="resume_profile_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume",
            evidence_refs=["artifact_resume", "artifact_diagnosis"],
            created_at=app_now(),
            updated_at=app_now(),
            raw_text_artifact_id="artifact_resume",
            diagnosis_artifact_id="artifact_diagnosis",
        )
    )
    store.save_career_profile(
        CareerProfile(
            career_profile_id="career_profile_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=["resume_profile_quality", "artifact_resume"],
            created_at=app_now(),
            updated_at=app_now(),
        )
    )
    store.save_jd_analysis(
        JDAnalysis(
            jd_analysis_id="jd_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd",
            evidence_refs=["artifact_jd"],
            created_at=app_now(),
            updated_at=app_now(),
        )
    )
    store.save_job_fit_report(
        JobFitReport(
            job_fit_report_id="fit_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd",
            evidence_refs=["resume_profile_quality", "career_profile_quality", "jd_quality", "artifact_report"],
            created_at=app_now(),
            updated_at=app_now(),
            jd_analysis_id="jd_quality",
            resume_profile_id="resume_profile_quality",
            career_profile_id="career_profile_quality",
            report_artifact_id="artifact_report",
        )
    )
    store.save_resume_version(
        ResumeVersion(
            resume_version_id="resume_version_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_resume_version",
            evidence_refs=[
                "resume_profile_quality",
                "jd_quality",
                "fit_quality",
                "artifact_resume",
                "artifact_resume_version",
            ],
            created_at=app_now(),
            updated_at=app_now(),
            base_resume_profile_id="resume_profile_quality",
            target_jd_analysis_id="jd_quality",
            title="质量门禁样本",
            format="markdown",
            artifact_id="artifact_resume_version",
            change_summary=["补充量化指标占位"],
        )
    )
    store.save_career_application(
        CareerApplication(
            application_id="application_quality",
            status=CareerRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id="artifact_jd",
            evidence_refs=["resume_profile_quality", "career_profile_quality", "jd_quality", "fit_quality"],
            created_at=app_now(),
            updated_at=app_now(),
            company="质量门禁公司",
            position="AI 应用开发工程师",
            stage="ready_to_apply",
            priority="medium",
            resume_profile_id="resume_profile_quality",
            career_profile_id="career_profile_quality",
            jd_analysis_id="jd_quality",
            job_fit_report_id="fit_quality",
            resume_version_ids=["resume_version_quality"],
        )
    )
