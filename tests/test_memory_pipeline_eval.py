"""Tests for the memory pipeline evaluation scenarios."""

from __future__ import annotations

from pathlib import Path
from argparse import Namespace

from scripts.eval_memory_pipeline import SCENARIOS, _apply_preset, _build_summary, _quality_gate_failures, run_case

__all__ = []


def test_memory_pipeline_eval_quality_scenarios_pass_with_fixture_model(tmp_path: Path) -> None:
    scenario_names = [
        "baseline",
        "preference_conflict",
        "architecture_override",
        "tool_failure_retry",
        "forbidden_memory",
    ]

    for name in scenario_names:
        report = run_case(
            scenario=SCENARIOS[name],
            event_count=36,
            real_model=False,
            keep_data=False,
            root_dir=tmp_path,
            max_input_tokens=5200,
            model_context_window_tokens=32768,
            model_input_ratio=0.35,
            skip_compaction=False,
        )

        assert report.pack_count == 1
        assert report.daily_coverage == 1.0, (name, report.daily_missing)
        assert report.facts_coverage == 1.0, (name, report.facts_missing)
        assert report.compaction_coverage == 1.0, (name, report.compaction_missing)
        assert report.daily_invalid_evidence_count == 0
        assert report.forbidden_fact_terms == []
        assert report.hallucination_terms == []
        assert report.retained_latest_tool_pair is True


def test_memory_pipeline_eval_fixture_preset_enables_quality_gate() -> None:
    args = Namespace(
        preset="fixture-regression",
        scenarios=["baseline"],
        events=[50],
        real_model=True,
        quality_gate=False,
    )

    resolved = _apply_preset(args)

    assert resolved.scenarios == ["all"]
    assert resolved.events == [36, 120]
    assert resolved.real_model is False
    assert resolved.quality_gate is True


def test_memory_pipeline_eval_quality_gate_detects_failures(tmp_path: Path) -> None:
    report = run_case(
        scenario=SCENARIOS["baseline"],
        event_count=36,
        real_model=False,
        keep_data=False,
        root_dir=tmp_path,
        max_input_tokens=5200,
        model_context_window_tokens=32768,
        model_input_ratio=0.35,
        skip_compaction=False,
    )
    report.daily_coverage = 0.5
    summary = _build_summary([report])

    failures = _quality_gate_failures(
        reports=[report],
        summary=summary,
        min_coverage=1.0,
        skip_compaction=False,
    )

    assert "min_daily_coverage < 1.0" in failures
