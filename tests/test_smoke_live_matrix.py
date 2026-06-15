from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.smoke_live_matrix import (
    INTERACTIVE_INTERVIEW_REVIEW_SCENARIOS,
    INTERACTIVE_RAG_TO_NOTE_SCENARIOS,
    P0_SCENARIOS,
    P1_SCENARIOS,
    ScenarioReport,
    _apply_live_quality_gate,
    _apply_product_stop_line,
    _apply_scenario_gates,
    _selected_scenarios,
    write_json_report,
)


def test_selected_scenarios_dedupes_all_p0_and_explicit() -> None:
    args = Namespace(all_p0=True, all_p1=False, scenario=["chat_only", "rag_to_note"])

    selected = _selected_scenarios(args)

    assert selected[: len(P0_SCENARIOS)] == list(P0_SCENARIOS)
    assert selected.count("chat_only") == 1
    assert selected[-1] == "rag_to_note"


def test_all_p1_includes_interactive_langgraph_scenarios() -> None:
    args = Namespace(all_p0=False, all_p1=True, scenario=None)

    selected = _selected_scenarios(args)

    assert selected == list(P1_SCENARIOS)
    assert INTERACTIVE_RAG_TO_NOTE_SCENARIOS <= set(selected)
    assert INTERACTIVE_INTERVIEW_REVIEW_SCENARIOS <= set(selected)


def test_chat_only_gate_rejects_tool_calls(tmp_path: Path) -> None:
    report = _report(tmp_path, scenario="chat_only", tool_call_counts={"memory_search": 1})

    _apply_scenario_gates(report)

    assert any("chat_only 不应调用工具" in error for error in report.errors)


def test_rag_read_only_gate_requires_retrieval_and_forbids_writes(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="rag_read_only",
        tool_call_counts={"retrieval_search": 1, "retrieval_context_pack": 1, "note_create": 1},
        write_tool_counts={"note_create": 1},
    )

    _apply_scenario_gates(report)

    assert any("不应调用写入工具" in error for error in report.errors)


def test_note_write_gate_separates_note_from_memory(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="note_write",
        tool_call_counts={"note_create": 1, "memory_write": 1},
        record_counts={"notes": 1},
    )

    _apply_scenario_gates(report)

    assert any("越界工具调用" in error for error in report.errors)


def test_interactive_rag_to_note_gate_requires_workflow_events_and_single_note_write(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="interactive_rag_to_note_source_select",
        tool_call_counts={"retrieval_search": 1, "retrieval_context_pack": 1, "note_create": 2},
        record_counts={"notes": 1},
        workflow_event_counts={"workflow_waiting_for_input": 1},
    )

    _apply_scenario_gates(report)

    assert any("note_create/note_append 不应超过 1 次" in error for error in report.errors)
    assert any("workflow_waiting_for_input" in error for error in report.errors)
    assert any("workflow_completed" in error for error in report.errors)


def test_interactive_rag_to_note_gate_accepts_completed_flow(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="interactive_rag_to_note_review_edit",
        tool_call_counts={"retrieval_search": 1, "retrieval_context_pack": 1, "note_create": 1},
        record_counts={"notes": 1},
        workflow_event_counts={"workflow_waiting_for_input": 2, "workflow_completed": 1},
    )

    _apply_scenario_gates(report)

    assert report.errors == []


def test_interactive_interview_review_gate_requires_exact_writes_and_workflow_events(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="interactive_interview_review_scope_select",
        tool_call_counts={
            "retrieval_search": 1,
            "retrieval_context_pack": 1,
            "note_create": 2,
            "career_application_merge": 0,
        },
        record_counts={"notes": 2, "career_applications": 1},
        workflow_event_counts={"workflow_waiting_for_input": 1},
    )

    _apply_scenario_gates(report)

    assert any("note_create 1 次" in error for error in report.errors)
    assert any("career_application_merge 1 次" in error for error in report.errors)
    assert any("workflow_waiting_for_input" in error for error in report.errors)
    assert any("workflow_completed" in error for error in report.errors)


def test_interactive_interview_review_gate_accepts_completed_flow(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="interactive_interview_review_review_edit",
        tool_call_counts={
            "retrieval_search": 1,
            "retrieval_context_pack": 1,
            "note_create": 1,
            "career_application_merge": 1,
        },
        record_counts={"notes": 2, "career_applications": 1},
        workflow_event_counts={"workflow_waiting_for_input": 2, "workflow_completed": 1},
    )

    _apply_scenario_gates(report)

    assert report.errors == []


def test_write_json_report_serializes_paths(tmp_path: Path) -> None:
    report = _report(tmp_path, scenario="chat_only")
    output = tmp_path / "report.json"

    write_json_report([report], output)

    content = output.read_text(encoding="utf-8")
    assert '"scenario": "chat_only"' in content
    assert str(tmp_path) in content


def test_matrix_live_quality_gate_records_error_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    report = _report(tmp_path, scenario="main_job_child")

    class FakeFinding:
        severity = "error"
        code = "final_answer_source_drift"

        def format(self) -> str:
            return "error / final_answer_source_drift: drift"

    monkeypatch.setattr(
        "tools.smoke_live_matrix.check_career_live_quality",
        lambda **_: type("FakeReport", (), {"findings": [FakeFinding()]})(),
    )

    stack = SimpleNamespace(session_repository=object(), career_store=object())

    _apply_live_quality_gate(stack=stack, report=report)  # type: ignore[arg-type]

    assert report.quality_error_codes == ["final_answer_source_drift"]
    assert any("Live 质量门禁错误" in error for error in report.errors)


def test_product_stop_line_rejects_harmful_duplicates(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="career_full",
        efficiency={"harmful_duplicate_tool_call_count": 1},
    )

    _apply_product_stop_line(report)

    assert any("有害重复工具调用" in error for error in report.errors)


def test_product_stop_line_rejects_hidden_runtime_results(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="career_full",
        efficiency={"hidden_tool_result_count": 1},
    )

    _apply_product_stop_line(report)

    assert any("hidden/runtime-hidden" in error for error in report.errors)


def test_product_stop_line_rejects_unrecovered_failed_tools(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="career_full",
        efficiency={
            "failed_tool_result_count": 1,
            "failed_tool_results": {"agent_main:career_resume_version_create": 1},
            "unrecovered_failed_tool_result_count": 1,
            "unrecovered_failed_tool_results": {"agent_main:career_resume_version_create": 1},
        },
    )

    _apply_product_stop_line(report)

    assert any("失败工具结果" in error for error in report.errors)


def test_product_stop_line_allows_recovered_protective_failed_tools(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="career_full",
        efficiency={
            "failed_tool_result_count": 1,
            "failed_tool_results": {"agent_main:career_resume_version_create": 1},
            "recovered_failed_tool_result_count": 1,
            "recovered_failed_tool_results": {"agent_main:career_resume_version_create": 1},
            "unrecovered_failed_tool_result_count": 0,
            "unrecovered_failed_tool_results": {},
        },
    )

    _apply_product_stop_line(report)

    assert report.errors == []


def test_product_stop_line_warns_for_cost_without_failing(tmp_path: Path) -> None:
    report = _report(
        tmp_path,
        scenario="chat_only",
        elapsed_seconds=31,
        efficiency={"total_llm_calls": 4, "total_llm_tokens": 12_000},
    )

    _apply_product_stop_line(report)

    assert report.errors == []
    assert len(report.warnings) == 3


def _report(
    tmp_path: Path,
    *,
    scenario: str,
    elapsed_seconds: float = 0,
    tool_call_counts: dict[str, int] | None = None,
    write_tool_counts: dict[str, int] | None = None,
    record_counts: dict[str, int] | None = None,
    efficiency: dict[str, object] | None = None,
    workflow_event_counts: dict[str, int] | None = None,
) -> ScenarioReport:
    return ScenarioReport(
        scenario=scenario,
        tier="P0",
        run_index=1,
        session_id="sess_live_matrix_test",
        data_dir=tmp_path,
        success=False,
        elapsed_seconds=elapsed_seconds,
        tool_call_counts=tool_call_counts or {},
        write_tool_counts=write_tool_counts or {},
        record_counts=record_counts or {},
        efficiency=efficiency or {},
        workflow_event_counts=workflow_event_counts or {},
    )
