from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.smoke_live_matrix import (
    P0_SCENARIOS,
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
    )
