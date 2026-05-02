"""Tests for the memory pipeline evaluation scenarios."""

from __future__ import annotations

from pathlib import Path

from scripts.eval_memory_pipeline import SCENARIOS, run_case

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
