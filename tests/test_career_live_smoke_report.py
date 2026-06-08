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
from app.core.time import app_now
from app.domain.models import EventRecord, SessionArtifact
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.learning.models import LearningRecordStatus, LearningTask
from app.learning.store import LearningStore

from tools.smoke_career_live_flow import (
    FlowReport,
    LiveStack,
    TurnReport,
    _prepare_clean_run_data_dir,
    _runtime_config_text,
    efficiency_summary,
    infer_failure_stage,
    inspect_flow_outputs,
    print_report,
    retrieval_quality_summary,
    run_all,
)


def test_live_smoke_prepares_clean_run_data_dir(tmp_path: Path) -> None:
    stale_file = tmp_path / "run_001" / "sessions" / "sess_old" / "metadata.json"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("{}", encoding="utf-8")

    run_dir = _prepare_clean_run_data_dir(tmp_path, 1)

    assert run_dir == tmp_path / "run_001"
    assert run_dir.exists()
    assert not stale_file.exists()
    assert list(run_dir.iterdir()) == []


def test_live_smoke_runtime_config_text() -> None:
    settings = SimpleNamespace(
        tool_schema_disclosure_mode="search",
        tool_context_window_mode="compact",
        workflow_rule_selection_mode="sparse",
    )

    assert _runtime_config_text(settings) == (
        "配置: TOOL_SCHEMA_DISCLOSURE_MODE=search "
        "TOOL_CONTEXT_WINDOW_MODE=compact "
        "WORKFLOW_RULE_SELECTION_MODE=sparse"
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


def test_live_smoke_report_prints_efficiency_summary(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    report = FlowReport(
        run_index=1,
        session_id="sess_live_career_efficiency",
        data_dir=tmp_path / "run_001",
        success=True,
        elapsed_seconds=12.34,
        efficiency={
            "llm_calls_by_agent": {"agent_main": 3, "job_agent": 2},
            "llm_tokens_by_agent": {"agent_main": 1200, "job_agent": 900},
            "llm_calls_by_phase": {"tool_loop": 4, "final_answer_recovery": 1},
            "llm_tokens_by_phase": {"tool_loop": 1500, "final_answer_recovery": 600},
            "llm_prompt_parts": {"system_prompt_estimate_tokens": 800, "messages_estimate_tokens": 500},
            "llm_system_prompt_sections": {"agent_identity": 300, "tool_catalog": 200},
            "duplicate_tool_calls": {"agent_main:tool_search:{\"query\":\"resume\"}": 2},
            "hidden_tool_results": {"job_agent:career_profile_get:tool_hidden_by_runtime_plan": 1},
            "failed_tool_results": {},
            "workflow_decisions": {"tool_loop_stagnation": 1},
            "total_llm_calls": 5,
            "total_llm_tokens": 2100,
            "total_prompt_tokens": 1800,
            "total_completion_tokens": 300,
            "final_answer_recovery_tokens": 600,
            "final_answer_recovery_calls": 1,
            "duplicate_tool_call_count": 1,
            "hidden_tool_result_count": 1,
            "failed_tool_result_count": 0,
        },
    )

    print_report([report])

    output = capsys.readouterr().out
    assert "效率摘要: avg_llm_calls=5.0" in output
    assert "avg_final_answer_recovery_tokens=600" in output
    assert "efficiency: llm_calls=" in output
    assert "cost_profile: phase_tokens=" in output
    assert "final_answer_recovery=600/1" in output
    assert "top_sections=" in output
    assert "duplicates=1" in output
    assert "stagnation=1" in output
    assert "duplicate_tools:" in output
    assert "hidden_tools:" in output


def test_live_smoke_efficiency_summary_reads_future_agent_event_files(tmp_path: Path) -> None:
    session_id = "sess_live_future_agent"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_llm_usage(
        repository,
        session_id=session_id,
        agent_id="research_agent",
        event_id="evt_future_agent_usage",
        total_tokens=321,
        prompt_tokens=300,
        completion_tokens=21,
        phase="tool_loop",
    )

    summary = efficiency_summary(repository, session_id)

    assert summary["llm_calls_by_agent"] == {"research_agent": 1}
    assert summary["llm_tokens_by_agent"] == {"research_agent": 321}


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
    _save_product_records(store, session_id=session_id, unsafe_resume_version=True)
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


def test_live_smoke_fails_when_final_answer_leaks_internal_runtime_text(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_internal_answer")
    report.turns = [
        TurnReport(
            name="项目动作：面试准备",
            answer='运行时工具状态摘要（完整工具结果见事件日志）： {"runtime_tool_state":"compact"}',
            elapsed_seconds=1.0,
            tool_calls=["career_application_get", "career_application_merge"],
        )
    ]
    stack.session_repository.append_agent_event(
        report.session_id,
        "agent_main",
        EventRecord(
            event_id="evt_internal_answer",
            session_id=report.session_id,
            type="assistant_message",
            payload={"content": '运行时工具状态摘要（完整工具结果见事件日志）： {"runtime_tool_state":"compact"}'},
            created_at=app_now(),
            agent_id="agent_main",
            run_id="run_test",
        ),
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "最终回答泄露内部 runtime 文案。" in report.errors
    assert "检测到 assistant_message 泄露内部 runtime 文案。" in report.errors
    assert report.failed_stage == "最终回答收束"


def test_live_smoke_fails_when_final_answer_contains_pseudo_tool_call(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_pseudo_tool_call_answer")
    pseudo_tool_call = (
        "<tool_call>\n"
        "<function=career_application_get>\n"
        "<parameter=application_id>application_alpha</parameter>\n"
        "</function>\n"
        "</tool_call>"
    )
    report.turns = [
        TurnReport(
            name="项目动作：面试准备",
            answer=pseudo_tool_call,
            elapsed_seconds=1.0,
            tool_calls=["career_application_get", "career_application_merge"],
        )
    ]
    stack.session_repository.append_agent_event(
        report.session_id,
        "agent_main",
        EventRecord(
            event_id="evt_pseudo_tool_call_answer",
            session_id=report.session_id,
            type="assistant_message",
            payload={"content": pseudo_tool_call},
            created_at=app_now(),
            agent_id="agent_main",
            run_id="run_test",
        ),
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "最终回答包含伪工具调用或不可交付弱答复。" in report.errors
    assert "检测到 assistant_message/agent_result_summary 包含伪工具调用或不可交付弱答复。" in report.errors
    assert report.failed_stage == "最终回答收束"


def test_live_smoke_fails_when_agent_result_summary_is_unusable(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_unusable_agent_summary")
    report.turns = [
        TurnReport(
            name="项目动作：面试准备",
            answer="面试准备材料已生成。",
            elapsed_seconds=1.0,
            tool_calls=["career_application_get", "career_application_merge"],
        )
    ]
    stack.session_repository.append_agent_event(
        report.session_id,
        "job_agent",
        EventRecord(
            event_id="evt_unusable_agent_summary",
            session_id=report.session_id,
            type="agent_result_summary",
            payload={"summary": "我无法处理你的请求。"},
            created_at=app_now(),
            agent_id="job_agent",
            run_id="run_test",
        ),
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "检测到 assistant_message/agent_result_summary 包含伪工具调用或不可交付弱答复。" in report.errors
    assert report.failed_stage == "最终回答收束"


@pytest.mark.parametrize(
    "answer",
    [
        "当前没有生成可用的最终答复。我已停止继续执行重复步骤，避免无效消耗；请补充关键信息后再试。",
        "当前 workflow 守卫限制了我的直接工具调用，我需要委派子任务来完成定制简历的创建和合并。",
    ],
)
def test_live_smoke_fails_when_final_answer_is_non_deliverable(answer: str, tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_non_deliverable_answer")
    report.turns = [
        TurnReport(
            name="项目动作：面试准备",
            answer=answer,
            elapsed_seconds=1.0,
            tool_calls=["career_application_get", "career_application_merge"],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "最终回答包含伪工具调用或不可交付弱答复。" in report.errors
    assert report.failed_stage == "最终回答收束"


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


def test_retrieval_quality_summary_reports_context_budget(tmp_path: Path) -> None:
    session_id = "sess_live_rag_quality"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_call_search",
        tool_name="retrieval_search",
        arguments={"query": "RAG 一面复盘", "top_k": 5},
        tool_call_id="call_search",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_result_search",
        tool_name="retrieval_search",
        success=True,
        content='{"hits":[{"source":{"source_type":"note","source_id":"note_1"}}]}',
        tool_call_id="call_search",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_call_pack",
        tool_name="retrieval_context_pack",
        arguments={"query": "RAG 一面复盘", "max_chars": 500},
        tool_call_id="call_pack",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_result_pack",
        tool_name="retrieval_context_pack",
        success=True,
        content=(
            '{"max_chars":500,"context_char_count":420,'
            '"context_pack":{"context_char_count":420,'
            '"hits":[{"source":{"source_type":"career_application","source_id":"application_1"}},'
            '{"source":{"source_type":"note","source_id":"note_1"}}]}}'
        ),
        tool_call_id="call_pack",
    )

    summary = retrieval_quality_summary(repository, session_id)

    assert summary["search_calls"] == 1
    assert summary["context_pack_calls"] == 1
    assert summary["max_context_chars"] == 420
    assert summary["max_requested_chars"] == 500
    assert summary["budget_violations"] == 0
    assert summary["source_type_counts"] == {"note": 2, "career_application": 1}


def test_efficiency_summary_reports_cost_duplicates_hidden_and_decisions(tmp_path: Path) -> None:
    session_id = "sess_live_efficiency"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_llm_usage(
        repository,
        session_id=session_id,
        agent_id="agent_main",
        event_id="evt_llm_main_1",
        total_tokens=100,
        prompt_tokens=80,
        completion_tokens=20,
        phase="tool_loop",
        prompt_parts={
            "system_prompt_estimate_tokens": 50,
            "messages_estimate_tokens": 20,
            "tools_estimate_tokens": 10,
        },
        system_prompt_sections=[
            {"name": "agent_identity", "tokens": 30},
            {"name": "tool_catalog", "tokens": 20},
        ],
    )
    _append_llm_usage(
        repository,
        session_id=session_id,
        agent_id="job_agent",
        event_id="evt_llm_job_1",
        total_tokens=250,
        prompt_tokens=210,
        completion_tokens=40,
        phase="final_answer_recovery",
        prompt_parts={
            "system_prompt_estimate_tokens": 70,
            "messages_estimate_tokens": 40,
            "tool_pending_message_estimate_tokens": 30,
        },
        system_prompt_sections=[
            {"name": "agent_identity", "tokens": 40},
            {"name": "assigned_task_context", "tokens": 30},
        ],
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_call_1",
        tool_name="session_create_text_artifact",
        arguments={"artifact_id": "artifact_report", "content": "first draft"},
        tool_call_id="call_1",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_call_2",
        tool_name="session_create_text_artifact",
        arguments={"artifact_id": "artifact_report", "content": "rewritten draft"},
        tool_call_id="call_2",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_call_3",
        tool_name="session_create_text_artifact",
        arguments={"artifact_id": "artifact_other", "content": "different artifact"},
        tool_call_id="call_3",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_hidden",
        tool_name="career_profile_get",
        success=True,
        content='{"workflow_runtime_result":true,"reason":"tool_hidden_by_runtime_plan"}',
        tool_call_id="call_hidden",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_failed",
        tool_name="career_job_fit_report_save",
        success=False,
        content="validation failed",
        tool_call_id="call_failed",
    )
    _append_workflow_decision(
        repository,
        session_id=session_id,
        agent_id="agent_main",
        event_id="evt_stagnation",
        reason="tool_loop_stagnation",
    )

    summary = efficiency_summary(repository, session_id)

    assert summary["llm_calls_by_agent"] == {"agent_main": 1, "job_agent": 1}
    assert summary["llm_tokens_by_agent"] == {"agent_main": 100, "job_agent": 250}
    assert summary["llm_calls_by_phase"] == {"final_answer_recovery": 1, "tool_loop": 1}
    assert summary["llm_tokens_by_phase"] == {"final_answer_recovery": 250, "tool_loop": 100}
    assert summary["llm_prompt_parts"]["system_prompt_estimate_tokens"] == 120
    assert summary["llm_prompt_parts"]["messages_estimate_tokens"] == 60
    assert summary["llm_prompt_parts"]["tools_estimate_tokens"] == 10
    assert summary["llm_prompt_parts"]["tool_pending_message_estimate_tokens"] == 30
    assert summary["llm_system_prompt_sections"] == {
        "agent_identity": 70,
        "assigned_task_context": 30,
        "tool_catalog": 20,
    }
    assert summary["final_answer_recovery_tokens_by_agent"] == {"job_agent": 250}
    assert summary["total_llm_calls"] == 2
    assert summary["total_llm_tokens"] == 350
    assert summary["total_prompt_tokens"] == 290
    assert summary["total_completion_tokens"] == 60
    assert summary["final_answer_recovery_calls"] == 1
    assert summary["final_answer_recovery_tokens"] == 250
    assert summary["duplicate_tool_call_count"] == 1
    assert summary["harmful_duplicate_tool_call_count"] == 1
    assert summary["recovery_duplicate_tool_call_count"] == 0
    assert summary["hidden_tool_result_count"] == 1
    assert summary["failed_tool_result_count"] == 1
    assert summary["recovered_failed_tool_result_count"] == 0
    assert summary["unrecovered_failed_tool_result_count"] == 1
    assert summary["workflow_decisions"] == {"tool_loop_stagnation": 1}


def test_efficiency_summary_separates_recovered_protective_failures(tmp_path: Path) -> None:
    session_id = "sess_live_recovered_protective_failure"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_failed_version",
        tool_name="career_resume_version_create",
        success=False,
        content=(
            "ResumeVersion validation failed: ResumeVersion content contains unverified quantitative metrics "
            "not present in the base resume artifact: 3 年后端开发与项目."
        ),
        tool_call_id="call_failed_version",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_success_version",
        tool_name="career_resume_version_create",
        success=True,
        content='{"record_type":"resume_version","record_id":"resume_version_alpha"}',
        tool_call_id="call_success_version",
    )

    summary = efficiency_summary(repository, session_id)

    assert summary["failed_tool_result_count"] == 1
    assert summary["failed_tool_results"] == {"agent_main:career_resume_version_create": 1}
    assert summary["recovered_failed_tool_result_count"] == 1
    assert summary["recovered_failed_tool_results"] == {"agent_main:career_resume_version_create": 1}
    assert summary["unrecovered_failed_tool_result_count"] == 0
    assert summary["unrecovered_failed_tool_results"] == {}


def test_efficiency_summary_separates_recovery_duplicates(tmp_path: Path) -> None:
    session_id = "sess_live_recovery_duplicate"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    for index, success, content in [
        (1, False, "ResumeVersion validation failed: invalid draft."),
        (2, True, '{"record_type":"resume_version","record_id":"resume_version_alpha"}'),
    ]:
        call_id = f"call_resume_version_{index}"
        _append_tool_call(
            repository,
            session_id=session_id,
            event_id=f"evt_resume_version_call_{index}",
            tool_name="career_resume_version_create",
            arguments={"title": "定制简历", "base_resume_profile_id": "resume_profile_alpha"},
            tool_call_id=call_id,
        )
        _append_tool_result(
            repository,
            session_id=session_id,
            event_id=f"evt_resume_version_result_{index}",
            tool_name="career_resume_version_create",
            success=success,
            content=content,
            tool_call_id=call_id,
        )

    summary = efficiency_summary(repository, session_id)

    assert summary["duplicate_tool_call_count"] == 1
    assert summary["recovery_duplicate_tool_call_count"] == 1
    assert summary["harmful_duplicate_tool_call_count"] == 0
    assert summary["recovery_duplicate_tool_calls"]
    assert not summary["harmful_duplicate_tool_calls"]


def test_efficiency_summary_treats_guard_block_retry_as_recovery_duplicate(tmp_path: Path) -> None:
    session_id = "sess_live_guard_retry_duplicate"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    for index, content in [
        (
            1,
            '{"workflow_runtime_result":true,"policy":"block",'
            '"reason":"job_fit_report_artifact_candidate_facts_conflict","result_created":false}',
        ),
        (2, '{"artifact_id":"artifact_report","title":"岗位匹配报告.md"}'),
    ]:
        call_id = f"call_report_{index}"
        _append_tool_call(
            repository,
            session_id=session_id,
            event_id=f"evt_report_call_{index}",
            tool_name="session_create_text_artifact",
            arguments={"title": "岗位匹配报告.md"},
            tool_call_id=call_id,
        )
        _append_tool_result(
            repository,
            session_id=session_id,
            event_id=f"evt_report_result_{index}",
            tool_name="session_create_text_artifact",
            success=True,
            content=content,
            tool_call_id=call_id,
        )

    summary = efficiency_summary(repository, session_id)

    assert summary["duplicate_tool_call_count"] == 1
    assert summary["recovery_duplicate_tool_call_count"] == 1
    assert summary["harmful_duplicate_tool_call_count"] == 0


def test_efficiency_summary_treats_replaced_hidden_duplicate_as_recovery_duplicate(tmp_path: Path) -> None:
    session_id = "sess_live_replaced_duplicate"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_version_call_1",
        tool_name="career_resume_version_create",
        arguments={"title": "定制简历"},
        tool_call_id="call_version_1",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_version_result_1",
        tool_name="career_resume_version_create",
        success=True,
        content='{"record_type":"resume_version","record_id":"resume_version_alpha"}',
        tool_call_id="call_version_1",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_version_call_2",
        tool_name="career_resume_version_create",
        arguments={"title": "定制简历"},
        tool_call_id="call_version_2",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_merge_call",
        tool_name="career_application_merge",
        arguments={"application_id": "application_alpha"},
        tool_call_id="call_version_2",
    )
    _append_tool_result(
        repository,
        session_id=session_id,
        event_id="evt_merge_result",
        tool_name="career_application_merge",
        success=True,
        content='{"record_type":"career_application","record_id":"application_alpha"}',
        tool_call_id="call_version_2",
    )

    summary = efficiency_summary(repository, session_id)

    assert summary["duplicate_tool_call_count"] == 1
    assert summary["recovery_duplicate_tool_call_count"] == 1
    assert summary["harmful_duplicate_tool_call_count"] == 0


def test_efficiency_summary_does_not_treat_distinct_application_merge_updates_as_duplicate(
    tmp_path: Path,
) -> None:
    session_id = "sess_live_distinct_application_merge_updates"
    repository = JsonlSessionRepository(data_dir=tmp_path)
    repository.create_session(session_id)
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_merge_resume_version",
        tool_name="career_application_merge",
        arguments={
            "application_id": "application_alpha",
            "updates": {"resume_version_ids": ["resume_version_alpha"]},
        },
        tool_call_id="call_merge_resume_version",
    )
    _append_tool_call(
        repository,
        session_id=session_id,
        event_id="evt_merge_interview_review",
        tool_name="career_application_merge",
        arguments={
            "application_id": "application_alpha",
            "updates": {
                "stage": "interviewing",
                "notes": "面试复盘已保存。",
                "next_actions": ["复习 RAG 评估"],
            },
        },
        tool_call_id="call_merge_interview_review",
    )

    summary = efficiency_summary(repository, session_id)

    assert summary["duplicate_tool_call_count"] == 0
    assert summary["harmful_duplicate_tool_call_count"] == 0


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


def test_live_smoke_report_fails_when_m12_note_writes_other_products(tmp_path: Path) -> None:
    session_id = "sess_live_m12_note"
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
                name="M12动作：召回保存笔记",
                answer="已保存笔记，同时错误创建了学习任务。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "note_create",
                    "learning_task_create",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M12 保存笔记动作出现越界写入工具: ['learning_task_create']" in report.errors


def test_live_smoke_report_fails_when_m12_pre_apply_reanalyzes_core_records(tmp_path: Path) -> None:
    session_id = "sess_live_m12_pre_apply"
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
                name="M12动作：召回投递前检查",
                answer="已完成检查，但错误重写了 JD 分析。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "career_jd_analysis_save",
                    "career_application_merge",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M12 投递前检查不应重新解析或保存核心画像: ['career_jd_analysis_save']" in report.errors


def test_live_smoke_report_fails_when_m16_review_skips_note_or_application_update(tmp_path: Path) -> None:
    session_id = "sess_live_m16_review_missing_write"
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
                name="M16动作：面试复盘更新项目",
                answer="只回答了复盘建议，但没有写入产品记录。",
                elapsed_seconds=1.0,
                tool_calls=["retrieval_search", "retrieval_context_pack"],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M16 面试复盘未写入 Note。" in report.errors
    assert "M16 面试复盘未更新 CareerApplication。" in report.errors


def test_live_smoke_report_fails_when_m16_review_crosses_boundaries(tmp_path: Path) -> None:
    session_id = "sess_live_m16_review_boundary"
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
                name="M16动作：面试复盘更新项目",
                answer="记录了复盘，但错误创建学习任务并重新委派。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "note_create",
                    "career_application_merge",
                    "delegate_agents",
                    "learning_task_create",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M16 面试复盘出现越界工具调用: ['delegate_agents', 'learning_task_create']" in report.errors


def test_live_smoke_report_fails_when_m17_advice_writes_products(tmp_path: Path) -> None:
    session_id = "sess_live_m17_advice_boundary"
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
                name="M17动作：复盘准备建议",
                answer="给出建议时错误创建任务并更新项目。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "career_application_merge",
                    "learning_task_create",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert (
        "M17 复盘准备建议只读动作出现写入或越界工具: "
        "['career_application_merge', 'learning_task_create']"
    ) in report.errors


def test_live_smoke_report_fails_when_m17_review_to_task_skips_task_or_updates_project(tmp_path: Path) -> None:
    session_id = "sess_live_m17_task_boundary"
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
                name="M17动作：复盘建议转学习任务",
                answer="只更新了项目，没有创建学习任务。",
                elapsed_seconds=1.0,
                tool_calls=[
                    "retrieval_search",
                    "retrieval_context_pack",
                    "career_application_merge",
                ],
            )
        ],
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M17 复盘建议转任务未创建 LearningTask。" in report.errors
    assert "M17 复盘建议转任务出现越界工具调用: ['career_application_merge']" in report.errors


def test_live_smoke_report_fails_when_m20_advice_writes_task(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_m20_advice_boundary")
    report.turns = [
        TurnReport(
            name="M20动作：只问准备建议",
            answer="给出建议时错误创建了学习任务。",
            elapsed_seconds=1.0,
            tool_calls=["retrieval_search", "retrieval_context_pack", "learning_task_create"],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M20 只问建议动作出现写入或越界工具: ['learning_task_create']" in report.errors


def test_live_smoke_report_fails_when_m20_confirm_skips_task_or_updates_project(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_m20_confirm_boundary")
    report.turns = [
        TurnReport(
            name="M20动作：确认建议加入学习任务",
            answer="错误更新了项目，但没有创建学习任务。",
            elapsed_seconds=1.0,
            tool_calls=["retrieval_search", "retrieval_context_pack", "career_application_merge"],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M20 确认加入动作未创建 LearningTask。" in report.errors
    assert "M20 确认加入动作出现越界工具调用: ['career_application_merge']" in report.errors


def test_live_smoke_report_fails_when_m20_checkin_skips_lookup_or_state_update(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_m20_checkin_boundary")
    report.turns = [
        TurnReport(
            name="M20动作：记录学习进度",
            answer="记录了进度，但没有先定位任务，也没有更新完成状态。",
            elapsed_seconds=1.0,
            tool_calls=["learning_checkin_create"],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M20 记录进度动作未先定位 LearningTask。" in report.errors
    assert "M20 记录进度动作未按明确完成状态更新 LearningTask。" in report.errors


def test_live_smoke_report_accepts_retrieval_lookup_before_m20_checkin(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_m20_checkin_retrieval")
    report.turns = [
        TurnReport(
            name="M20动作：记录学习进度",
            answer="先用召回定位到 learning_task_alpha，再记录进度并更新状态。",
            elapsed_seconds=1.0,
            tool_calls=[
                "retrieval_search",
                "learning_checkin_create",
                "learning_task_update_state",
            ],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert "M20 记录进度动作未先定位 LearningTask。" not in report.errors


def test_live_smoke_report_fails_when_m20_confirm_task_misses_core_evidence_refs(tmp_path: Path) -> None:
    session_id = "sess_live_m20_confirm_evidence"
    report, base_stack = _base_report_and_stack(tmp_path, session_id=session_id)
    learning_store = LearningStore(root_dir=tmp_path / "learning", clock=app_now)
    learning_store.save_learning_task(
        LearningTask(
            learning_task_id="learning_task_confirm_missing_refs",
            status=LearningRecordStatus.ACTIVE,
            source_session_id=session_id,
            source_artifact_id=None,
            evidence_refs=["note_review_missing_core_refs"],
            created_at=app_now(),
            updated_at=app_now(),
            title="补齐 RAG 评估指标表达",
            progress_notes="来源：面试复盘建议",
        )
    )
    stack = cast(
        LiveStack,
        SimpleNamespace(
            session_repository=base_stack.session_repository,
            career_store=base_stack.career_store,
            learning_store=learning_store,
            data_dir=tmp_path,
        ),
    )
    report.turns = [
        TurnReport(
            name="M20动作：确认建议加入学习任务",
            answer="已创建学习任务。",
            elapsed_seconds=1.0,
            tool_calls=["retrieval_search", "learning_task_create"],
        )
    ]

    inspect_flow_outputs(stack=stack, report=report)

    assert not report.success
    assert "M20 确认加入动作未保留 application、复盘 note、匹配报告证据引用。" in report.errors


def test_live_smoke_report_warns_when_protective_tool_failure_recovers(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_recovered_protection")
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_failed_resume_version",
        tool_name="career_resume_version_create",
        success=False,
        content=(
            "ResumeVersion change_summary contains forbidden placeholder or replacement wording. "
            "Remove that wording; describe only verified changes or missing-fact risks."
        ),
        tool_call_id="call_failed_resume_version",
    )
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_recovered_resume_version",
        tool_name="career_resume_version_create",
        success=True,
        content='{"record_type":"resume_version","record_id":"resume_version_quality"}',
        tool_call_id="call_recovered_resume_version",
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert report.success
    assert report.failed_tools == []
    assert not report.errors
    assert report.warnings == [
        "已恢复的工具保护性拒绝: career_resume_version_create -> "
        "ResumeVersion change_summary contains forbidden placeholder or replacement wording. "
        "Remove that wording; describe only verified changes or missing-fact risks."
    ]


def test_live_smoke_report_warns_when_unverified_metric_failure_recovers(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_recovered_metric")
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_failed_resume_version_metric",
        tool_name="career_resume_version_create",
        success=False,
        content=(
            "ResumeVersion validation failed: ResumeVersion content contains unverified quantitative metrics "
            "not present in the base resume artifact: 40%, 68%."
        ),
        tool_call_id="call_failed_resume_version_metric",
    )
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_recovered_resume_version_metric",
        tool_name="career_resume_version_create",
        success=True,
        content='{"record_type":"resume_version","record_id":"resume_version_quality"}',
        tool_call_id="call_recovered_resume_version_metric",
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert report.success
    assert report.failed_tools == []
    assert not report.errors
    assert report.warnings == [
        "已恢复的工具保护性拒绝: career_resume_version_create -> "
        "ResumeVersion validation failed: ResumeVersion content contains unverified quantitative metrics "
        "not present in the base resume artifact: 40%, 68%."
    ]


def test_live_smoke_report_warns_when_unsupported_fact_failure_recovers(tmp_path: Path) -> None:
    report, stack = _base_report_and_stack(tmp_path, session_id="sess_live_recovered_unsupported_fact")
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_failed_resume_version_fact",
        tool_name="career_resume_version_create",
        success=False,
        content=(
            "ResumeVersion validation failed: ResumeVersion content/change_summary/keyword_strategy "
            "contains unsupported candidate tech facts: mysql, vector_search."
        ),
        tool_call_id="call_failed_resume_version_fact",
    )
    _append_tool_result(
        stack.session_repository,
        session_id=report.session_id,
        event_id="evt_recovered_resume_version_fact",
        tool_name="career_resume_version_create",
        success=True,
        content='{"record_type":"resume_version","record_id":"resume_version_quality"}',
        tool_call_id="call_recovered_resume_version_fact",
    )

    inspect_flow_outputs(stack=stack, report=report)

    assert report.success
    assert report.failed_tools == []
    assert not report.errors
    assert report.warnings == [
        "已恢复的工具保护性拒绝: career_resume_version_create -> "
        "ResumeVersion validation failed: ResumeVersion content/change_summary/keyword_strategy "
        "contains unsupported candidate tech facts: mysql, vector_search."
    ]


def _base_report_and_stack(tmp_path: Path, *, session_id: str) -> tuple[FlowReport, LiveStack]:
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
    )
    stack = cast(LiveStack, SimpleNamespace(session_repository=repository, career_store=store, data_dir=tmp_path))
    return report, stack


def _append_tool_result(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    event_id: str,
    tool_name: str,
    success: bool,
    content: str,
    tool_call_id: str,
) -> None:
    repository.append_agent_event(
        session_id,
        "agent_main",
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type="tool_result",
            payload={
                "tool_name": tool_name,
                "success": success,
                "content": content,
                "tool_call_id": tool_call_id,
            },
            created_at=app_now(),
            agent_id="agent_main",
            run_id="run_test",
        ),
    )


def _append_llm_usage(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    agent_id: str,
    event_id: str,
    total_tokens: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    phase: str | None = None,
    prompt_parts: dict[str, int] | None = None,
    system_prompt_sections: list[dict[str, object]] | None = None,
) -> None:
    payload: dict[str, object] = {
        "total_tokens": total_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    if phase is not None:
        payload["phase"] = phase
    if prompt_parts:
        payload.update(prompt_parts)
    if system_prompt_sections is not None:
        payload["system_prompt_sections"] = system_prompt_sections
    repository.append_agent_event(
        session_id,
        agent_id,
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type="llm_usage",
            payload=payload,
            created_at=app_now(),
            agent_id=agent_id,
            run_id="run_test",
        ),
    )


def _append_workflow_decision(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    agent_id: str,
    event_id: str,
    reason: str,
) -> None:
    repository.append_agent_event(
        session_id,
        agent_id,
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type="workflow_runtime_decision",
            payload={"reason": reason},
            created_at=app_now(),
            agent_id=agent_id,
            run_id="run_test",
        ),
    )


def _append_tool_call(
    repository: JsonlSessionRepository,
    *,
    session_id: str,
    event_id: str,
    tool_name: str,
    arguments: dict[str, object],
    tool_call_id: str,
) -> None:
    repository.append_agent_event(
        session_id,
        "agent_main",
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type="tool_call",
            payload={
                "name": tool_name,
                "arguments": arguments,
                "tool_call_id": tool_call_id,
            },
            created_at=app_now(),
            agent_id="agent_main",
            run_id="run_test",
        ),
    )


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


def _save_product_records(
    store: CareerProductStore,
    *,
    session_id: str,
    unsafe_resume_version: bool = False,
) -> None:
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
            change_summary=["强化 RAG 项目描述"] if not unsafe_resume_version else ["补充量化指标占位"],
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
