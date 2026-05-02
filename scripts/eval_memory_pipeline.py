"""Evaluate mid-term flush and context compaction quality.

This script is intentionally outside the production runtime. It builds synthetic
sessions with known critical facts, runs flush + compaction, and reports both
latency and preservation metrics.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from app.core.settings import Settings
from app.domain.models import EventRecord, RunContext
from app.domain.protocols import ChatModelClient, ModelResponse, StreamChunk
from app.infra.llm.openai_compatible_client import OpenAICompatibleClient
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.context_compactor import ContextCompactionConfig, ContextCompactor
from app.runtime.mid_term.event_packer import MidTermEventPackBuilder
from app.runtime.mid_term.models import FlushCursor
from app.runtime.mid_term_flusher import MidTermFlusher


@dataclass(slots=True)
class CriticalItem:
    label: str
    keywords: list[str]


@dataclass(slots=True)
class ModelCallMetric:
    kind: str
    elapsed_ms: float
    prompt_chars: int
    response_chars: int


@dataclass(slots=True)
class EvalScenario:
    name: str
    critical_items: list[CriticalItem]
    fact_items: list[CriticalItem]
    forbidden_terms: list[str]
    forbidden_fact_terms: list[str]
    latest_tool_call_id: str | None
    append_events: Callable[[JsonlSessionRepository, str, int], None]


@dataclass(frozen=True, slots=True)
class EvalPreset:
    scenarios: list[str]
    events: list[int]
    real_model: bool
    quality_gate: bool


@dataclass(slots=True)
class CaseReport:
    case_name: str
    event_count: int
    mode: str
    data_dir: str
    model_context_window_tokens: int
    model_input_ratio: float
    max_input_tokens: int
    pack_build_ms: float
    flush_total_ms: float
    compaction_total_ms: float
    pack_count: int
    pack_event_counts: list[int]
    pack_token_estimates: list[int]
    daily_path: str | None
    daily_chars: int
    daily_coverage: float
    daily_missing: list[str]
    daily_invalid_evidence_count: int
    daily_tool_pair_progress_count: int
    facts_chars: int
    facts_coverage: float
    facts_missing: list[str]
    forbidden_fact_terms: list[str]
    compaction_compacted: bool
    compaction_reason: str
    compaction_original_events: int
    compaction_compressed_events: int
    compaction_retained_events: int
    compaction_summary_chars: int
    compaction_coverage: float
    compaction_missing: list[str]
    retained_latest_tool_pair: bool
    hallucination_terms: list[str]
    model_calls: list[ModelCallMetric]

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["model_calls"] = [asdict(item) for item in self.model_calls]
        return payload


class InstrumentedModelClient:
    def __init__(self, delegate: ChatModelClient) -> None:
        self._delegate = delegate
        self.calls: list[ModelCallMetric] = []

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        prompt_chars = len(system_prompt) + sum(len(str(item.get("content", ""))) for item in messages)
        kind = _classify_model_call(system_prompt)
        started = time.perf_counter()
        response = self._delegate.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.calls.append(
            ModelCallMetric(
                kind=kind,
                elapsed_ms=elapsed_ms,
                prompt_chars=prompt_chars,
                response_chars=len(response.content),
            )
        )
        return response

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        if response.content:
            yield StreamChunk(delta=response.content, finished=False, has_tool_call_delta=False)
        yield StreamChunk(delta="", tool_calls=response.tool_calls, finished=True, has_tool_call_delta=False)


class FixtureModelClient:
    """Deterministic model for baseline structural evaluation."""

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = tools
        if "mid-term memory distillation" in system_prompt:
            return ModelResponse(content=json.dumps(_build_mid_term_summary(messages), ensure_ascii=False), tool_calls=[])
        if "session context compactor" in system_prompt:
            return ModelResponse(content=json.dumps(_build_compaction_summary(messages), ensure_ascii=False), tool_calls=[])
        return ModelResponse(content="{}", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[StreamChunk]:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        yield StreamChunk(delta=response.content, finished=True, has_tool_call_delta=False)


BASELINE_CRITICAL_ITEMS = [
    CriticalItem("latest_name", ["小明"]),
    CriticalItem("quality_goal", ["flush 速度", "daily 保真率", "context compaction"]),
    CriticalItem("tool_pair_rule", ["tool_call", "tool_result", "成对"]),
    CriticalItem("rolling_question", ["rolling.md", "归并"]),
    CriticalItem("artifact_reference", ["MEMORY_DEV_PROGRESS.md"]),
    CriticalItem("latest_tool_result", ["最新名字是小明"]),
]

FORBIDDEN_TERMS = ["张三", "火星", "Redis 缓存", "已经上线生产"]

SCENARIOS: dict[str, EvalScenario] = {
    "baseline": EvalScenario(
        name="baseline",
        critical_items=BASELINE_CRITICAL_ITEMS,
        fact_items=[
            CriticalItem("latest_name_fact", ["小明"]),
        ],
        forbidden_terms=[],
        forbidden_fact_terms=[],
        latest_tool_call_id="call_latest_name",
        append_events=lambda repo, session_id, event_count: _append_baseline_events(
            repo=repo,
            session_id=session_id,
            event_count=event_count,
        ),
    ),
    "preference_conflict": EvalScenario(
        name="preference_conflict",
        critical_items=[
            CriticalItem("latest_name_xiaowang", ["小王"]),
            CriticalItem("name_correction_chain", ["小猪", "小明", "小王"]),
            CriticalItem("latest_name_tool_result", ["最新名字是小王"]),
        ],
        fact_items=[CriticalItem("latest_name_fact", ["小王"])],
        forbidden_terms=["用户最新名字是小猪。", "用户最新名字是小明。"],
        forbidden_fact_terms=["用户最新名字是小猪", "用户最新名字是小明"],
        latest_tool_call_id="call_final_name",
        append_events=lambda repo, session_id, event_count: _append_preference_conflict_events(
            repo=repo,
            session_id=session_id,
            event_count=event_count,
        ),
    ),
    "architecture_override": EvalScenario(
        name="architecture_override",
        critical_items=[
            CriticalItem("filesystem_decision", ["文件系统", "主存储"]),
            CriticalItem("sqlite_override", ["sqlite", "派生 index"]),
        ],
        fact_items=[CriticalItem("architecture_fact", ["文件系统", "主存储"])],
        forbidden_terms=["sqlite 做主存储"],
        forbidden_fact_terms=["sqlite 做主存储"],
        latest_tool_call_id=None,
        append_events=lambda repo, session_id, event_count: _append_architecture_override_events(
            repo=repo,
            session_id=session_id,
            event_count=event_count,
        ),
    ),
    "tool_failure_retry": EvalScenario(
        name="tool_failure_retry",
        critical_items=[
            CriticalItem("failed_tool_result", ["失败", "文件不存在"]),
            CriticalItem("successful_retry", ["MEMORY_DEV_PROGRESS.md", "成功"]),
        ],
        fact_items=[],
        forbidden_terms=[],
        forbidden_fact_terms=[],
        latest_tool_call_id="call_read_progress",
        append_events=lambda repo, session_id, event_count: _append_tool_failure_retry_events(
            repo=repo,
            session_id=session_id,
            event_count=event_count,
        ),
    ),
    "forbidden_memory": EvalScenario(
        name="forbidden_memory",
        critical_items=[
            CriticalItem("temporary_secret_context", ["临时暗号", "不要记住"]),
        ],
        fact_items=[],
        forbidden_terms=[],
        forbidden_fact_terms=["临时暗号", "蓝鲸"],
        latest_tool_call_id=None,
        append_events=lambda repo, session_id, event_count: _append_forbidden_memory_events(
            repo=repo,
            session_id=session_id,
            event_count=event_count,
        ),
    ),
}

EVAL_PRESETS: dict[str, EvalPreset] = {
    "fixture-regression": EvalPreset(
        scenarios=["all"],
        events=[36, 120],
        real_model=False,
        quality_gate=True,
    ),
    "real-smoke": EvalPreset(
        scenarios=["preference_conflict", "architecture_override", "forbidden_memory"],
        events=[36],
        real_model=True,
        quality_gate=True,
    ),
}


def main() -> None:
    args = _apply_preset(_parse_args())
    reports: list[CaseReport] = []
    root_dir = Path(args.output_dir).resolve() if args.output_dir else None
    if root_dir is not None:
        root_dir.mkdir(parents=True, exist_ok=True)

    scenarios = _select_scenarios(args.scenarios)
    for scenario in scenarios:
        for event_count in args.events:
            report = run_case(
                scenario=scenario,
                event_count=max(24, event_count),
                real_model=args.real_model,
                keep_data=args.keep_data,
                root_dir=root_dir,
                max_input_tokens=args.max_input_tokens,
                model_context_window_tokens=args.model_context_window_tokens,
                model_input_ratio=args.model_input_ratio,
                skip_compaction=args.skip_compaction,
            )
            reports.append(report)
            _print_case_summary(report)

    summary = _build_summary(reports)
    payload = {
        "created_at": _format_time(datetime.now(UTC)),
        "mode": "real" if args.real_model else "fixture",
        "reports": [item.to_payload() for item in reports],
        "summary": summary,
    }
    report_path = Path(args.report).resolve() if args.report else Path(tempfile.gettempdir()) / "memory_pipeline_eval_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\nreport_path={report_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.quality_gate:
        failures = _quality_gate_failures(
            reports=reports,
            summary=summary,
            min_coverage=args.min_coverage,
            skip_compaction=args.skip_compaction,
        )
        if failures:
            for failure in failures:
                print(f"quality_gate_failed: {failure}", file=sys.stderr)
            raise SystemExit(2)


def run_case(
    *,
    scenario: EvalScenario | None = None,
    event_count: int,
    real_model: bool,
    keep_data: bool,
    root_dir: Path | None,
    max_input_tokens: int,
    model_context_window_tokens: int,
    model_input_ratio: float,
    skip_compaction: bool,
) -> CaseReport:
    resolved_scenario = scenario or SCENARIOS["baseline"]
    data_dir = _make_data_dir(root_dir=root_dir, event_count=event_count, scenario_name=resolved_scenario.name)
    session_id = f"sess_eval_{resolved_scenario.name}_{event_count}"
    print(
        f"start case scenario={resolved_scenario.name} events={event_count} "
        f"mode={'real' if real_model else 'fixture'} data_dir={data_dir}",
        flush=True,
    )
    context = _context(session_id)
    repo = JsonlSessionRepository(data_dir=data_dir)
    repo.create_session(session_id)
    resolved_scenario.append_events(repo, session_id, event_count)

    memory_store = FileMemoryStore(root_dir=data_dir / "memory")
    model = InstrumentedModelClient(_build_model_client(real_model=real_model))

    pack_builder = MidTermEventPackBuilder(
        repo,
        model_context_window_tokens=model_context_window_tokens,
        model_input_ratio=model_input_ratio,
        model_output_reserve_tokens=600,
        prompt_overhead_tokens=400,
        max_input_tokens=max_input_tokens,
    )
    started = time.perf_counter()
    packs, pack_reason = pack_builder.build(context=context, cursor=FlushCursor(last_event_id=None, last_flushed_at=None))
    pack_build_ms = (time.perf_counter() - started) * 1000
    if not packs:
        raise RuntimeError(f"event pack build failed: {pack_reason}")
    print(f"pack built events={event_count} packs={len(packs)} pack_ms={pack_build_ms:.1f}", flush=True)

    flusher = MidTermFlusher(
        session_repository=repo,
        memory_store=memory_store,
        model_client=model,
        model_context_window_tokens=model_context_window_tokens,
        model_input_ratio=model_input_ratio,
        model_output_reserve_tokens=600,
        prompt_overhead_tokens=400,
        max_input_tokens=max_input_tokens,
    )
    started = time.perf_counter()
    flush_result = flusher.flush_for_run_finished(context)
    flush_total_ms = (time.perf_counter() - started) * 1000
    if not flush_result.flushed:
        raise RuntimeError(f"flush failed: reason={flush_result.reason} status={flush_result.job_status}")
    print(f"flush done events={event_count} flush_ms={flush_total_ms:.1f}", flush=True)

    daily_path = Path(flush_result.daily_path) if flush_result.daily_path else None
    daily_text = daily_path.read_text(encoding="utf-8") if daily_path and daily_path.exists() else ""
    original_events = repo.list_events(session_id)
    valid_event_ids = {event.event_id for event in original_events}
    daily_coverage, daily_missing = _coverage(daily_text, resolved_scenario.critical_items)
    invalid_evidence_count = _invalid_evidence_count(daily_text, valid_event_ids)
    daily_tool_pair_progress_count = daily_text.count("[CALL]") if "[RESULT]" in daily_text else 0
    facts_text = _read_agent_facts_text(memory_store.root_dir, context.agent_id)
    facts_coverage, facts_missing = _coverage(facts_text, resolved_scenario.fact_items)
    forbidden_fact_terms = [term for term in resolved_scenario.forbidden_fact_terms if term in facts_text]

    if skip_compaction:
        compaction_total_ms = 0.0
        compacted_events = repo.list_events(session_id)
        compaction_coverage = 0.0
        compaction_missing = [item.label for item in resolved_scenario.critical_items]
        compaction_summary_chars = 0
        retained_latest_tool_pair = _retained_tool_pair(
            compacted_events,
            resolved_scenario.latest_tool_call_id,
            original_events=original_events,
        )
        compaction_payload = {
            "compacted": False,
            "reason": "skipped",
            "original_event_count": len(compacted_events),
            "compressed_event_count": 0,
            "retained_event_count": 0,
        }
    else:
        compactor = ContextCompactor(
            session_repository=repo,
            model_client=model,
            config=ContextCompactionConfig(
                enabled=True,
                trigger_event_count=max(10, event_count // 3),
                retain_event_count=8,
                model_context_window_tokens=model_context_window_tokens,
                trigger_token_count=1200,
            ),
        )
        started = time.perf_counter()
        compaction_result = compactor.compact_after_flush(context)
        compaction_total_ms = (time.perf_counter() - started) * 1000
        compacted_events = repo.list_events(session_id)
        compaction_text = _events_to_text(compacted_events)
        compaction_coverage, compaction_missing = _coverage(compaction_text, resolved_scenario.critical_items)
        summary_event = compacted_events[0] if compacted_events and compacted_events[0].type == "context_summary" else None
        compaction_summary_chars = len(json.dumps(summary_event.payload, ensure_ascii=False)) if summary_event else 0
        retained_latest_tool_pair = _retained_tool_pair(
            compacted_events,
            resolved_scenario.latest_tool_call_id,
            original_events=original_events,
        )
        compaction_payload = {
            "compacted": compaction_result.compacted,
            "reason": compaction_result.reason,
            "original_event_count": compaction_result.original_event_count,
            "compressed_event_count": compaction_result.compressed_event_count,
            "retained_event_count": compaction_result.retained_event_count,
        }
        print(f"compaction done events={event_count} compaction_ms={compaction_total_ms:.1f}", flush=True)
    compaction_text = _events_to_text(compacted_events)
    forbidden_terms = [*FORBIDDEN_TERMS, *resolved_scenario.forbidden_terms]
    hallucination_terms = [term for term in forbidden_terms if term in daily_text or term in compaction_text]

    report = CaseReport(
        case_name=resolved_scenario.name,
        event_count=event_count,
        mode="real" if real_model else "fixture",
        data_dir=str(data_dir),
        model_context_window_tokens=model_context_window_tokens,
        model_input_ratio=model_input_ratio,
        max_input_tokens=max_input_tokens,
        pack_build_ms=pack_build_ms,
        flush_total_ms=flush_total_ms,
        compaction_total_ms=compaction_total_ms,
        pack_count=len(packs),
        pack_event_counts=[pack.event_count for pack in packs],
        pack_token_estimates=[pack.input_estimated_tokens for pack in packs],
        daily_path=str(daily_path) if daily_path else None,
        daily_chars=len(daily_text),
        daily_coverage=daily_coverage,
        daily_missing=daily_missing,
        daily_invalid_evidence_count=invalid_evidence_count,
        daily_tool_pair_progress_count=daily_tool_pair_progress_count,
        facts_chars=len(facts_text),
        facts_coverage=facts_coverage,
        facts_missing=facts_missing,
        forbidden_fact_terms=forbidden_fact_terms,
        compaction_compacted=bool(compaction_payload["compacted"]),
        compaction_reason=str(compaction_payload["reason"]),
        compaction_original_events=int(compaction_payload["original_event_count"]),
        compaction_compressed_events=int(compaction_payload["compressed_event_count"]),
        compaction_retained_events=int(compaction_payload["retained_event_count"]),
        compaction_summary_chars=compaction_summary_chars,
        compaction_coverage=compaction_coverage,
        compaction_missing=compaction_missing,
        retained_latest_tool_pair=retained_latest_tool_pair,
        hallucination_terms=hallucination_terms,
        model_calls=model.calls,
    )
    if not keep_data:
        shutil.rmtree(data_dir, ignore_errors=True)
    return report


def _append_baseline_events(*, repo: JsonlSessionRepository, session_id: str, event_count: int) -> None:
    base_time = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    rows: list[tuple[str, dict[str, Any]]] = [
        ("user_message", {"content": "我的名字先叫小猪，但这只是旧称呼，后面如果改名要以最新为准。"}),
        ("assistant_message", {"content": "已记录旧称呼，后续会以最新纠正为准。"}),
        ("user_message", {"content": "架构决策：mid-term flush 必须保留 tool_call 和 tool_result 成对证据。"}),
        (
            "tool_call",
            {"name": "memory_search", "arguments": {"query": "用户名字"}, "tool_call_id": "call_initial_name"},
        ),
        (
            "tool_result",
            {
                "tool_name": "memory_search",
                "success": True,
                "content": "命中旧名字小猪，但后续需要允许纠正。",
                "tool_call_id": "call_initial_name",
            },
        ),
    ]
    filler_target = max(0, event_count - 13)
    for index in range(filler_target):
        kind = index % 4
        turn = index // 4
        if kind == 0:
            rows.append(("user_message", {"content": f"第 {turn} 轮继续讨论 memory pipeline 质量和性能。"}))
        elif kind == 1:
            rows.append(
                (
                    "tool_call",
                    {
                        "name": "memory_search",
                        "arguments": {"query": f"pipeline quality {turn}"},
                        "tool_call_id": f"call_noise_{turn}",
                    },
                )
            )
        elif kind == 2:
            rows.append(
                (
                    "tool_result",
                    {
                        "tool_name": "memory_search",
                        "success": True,
                        "content": f"返回第 {turn} 轮 pipeline 相关上下文。",
                        "tool_call_id": f"call_noise_{turn}",
                    },
                )
            )
        else:
            rows.append(("assistant_message", {"content": f"第 {turn} 轮已整理。"}))

    rows.extend(
        [
            ("user_message", {"content": "我把名字改成小明，以后叫小明，不要再叫小猪。"}),
            (
                "user_message",
                {
                    "content": (
                        "当前目标：先验证 flush 速度、daily 保真率、context compaction "
                        "关键内容保留率，再继续产品化。"
                    )
                },
            ),
            ("user_message", {"content": "开放问题：rolling.md 是否需要 daily 到 rolling 的后台归并器。"}),
            (
                "user_message",
                {
                    "content": (
                        "需要回溯 MEMORY_DEV_PROGRESS.md 和 "
                        "CONTEXT_ASSEMBLER_MULTI_AGENT_DESIGN_2026-04-29.md。"
                    )
                },
            ),
            (
                "tool_call",
                {"name": "memory_search", "arguments": {"query": "最新名字"}, "tool_call_id": "call_latest_name"},
            ),
            (
                "tool_result",
                {
                    "tool_name": "memory_search",
                    "success": True,
                    "content": "查询结果：最新名字是小明，旧称呼小猪已被覆盖。",
                    "tool_call_id": "call_latest_name",
                },
            ),
            ("assistant_message", {"content": "后续应以小明作为用户名字，并优先评估 flush 和 compaction 质量。"}),
            (
                "run_finished",
                {"answer_length": 34, "tool_calls": 2, "final_focus": "memory pipeline evaluation"},
            ),
        ]
    )

    for index, (event_type, payload) in enumerate(rows[:event_count]):
        _append_eval_event(
            repo=repo,
            session_id=session_id,
            event_id=f"evt_eval_{index:04d}",
            event_type=event_type,
            payload=payload,
            created_at=base_time + timedelta(seconds=index),
        )


def _append_preference_conflict_events(*, repo: JsonlSessionRepository, session_id: str, event_count: int) -> None:
    rows: list[tuple[str, dict[str, Any]]] = [
        ("user_message", {"content": "先记一下，我的名字叫小猪。"}),
        ("assistant_message", {"content": "已记录名字为小猪。"}),
        ("user_message", {"content": "我改名为小明，之前的小猪作废。"}),
        ("assistant_message", {"content": "已按最新纠正改为小明。"}),
        ("user_message", {"content": "最终确认：以后叫我小王，小猪和小明都不是最新名字。"}),
        (
            "tool_call",
            {"name": "memory_search", "arguments": {"query": "最新名字"}, "tool_call_id": "call_final_name"},
        ),
        (
            "tool_result",
            {
                "tool_name": "memory_search",
                "success": True,
                "content": "查询结果：最新名字是小王，小猪和小明都已过期。",
                "tool_call_id": "call_final_name",
            },
        ),
        ("assistant_message", {"content": "后续应以小王作为用户最新名字。"}),
        ("run_finished", {"answer_length": 18, "tool_calls": 1}),
    ]
    _append_rows_with_filler(repo=repo, session_id=session_id, rows=rows, event_count=event_count)


def _append_architecture_override_events(*, repo: JsonlSessionRepository, session_id: str, event_count: int) -> None:
    rows: list[tuple[str, dict[str, Any]]] = [
        ("user_message", {"content": "先讨论一个方案：sqlite 做 memory 主存储。"}),
        ("assistant_message", {"content": "已记录 sqlite 主存储作为早期候选方案。"}),
        (
            "user_message",
            {
                "content": (
                    "最终架构决策：memory 主存储使用文件系统，sqlite 暂不接入，"
                    "以后最多只考虑作为派生 index。"
                )
            },
        ),
        ("assistant_message", {"content": "已改为文件系统主存储，sqlite 只作为未来派生 index 的候选。"}),
        ("run_finished", {"answer_length": 42, "tool_calls": 0}),
    ]
    _append_rows_with_filler(repo=repo, session_id=session_id, rows=rows, event_count=event_count)


def _append_tool_failure_retry_events(*, repo: JsonlSessionRepository, session_id: str, event_count: int) -> None:
    rows: list[tuple[str, dict[str, Any]]] = [
        ("user_message", {"content": "读取不存在的配置文件，看看错误如何进入 daily。"}),
        (
            "tool_call",
            {"name": "session_read_file", "arguments": {"path": "missing_config.md"}, "tool_call_id": "call_missing"},
        ),
        (
            "tool_result",
            {
                "tool_name": "session_read_file",
                "success": False,
                "content": "失败：文件不存在 missing_config.md。",
                "tool_call_id": "call_missing",
            },
        ),
        ("user_message", {"content": "改为读取 MEMORY_DEV_PROGRESS.md。"}),
        (
            "tool_call",
            {
                "name": "session_read_file",
                "arguments": {"path": "MEMORY_DEV_PROGRESS.md"},
                "tool_call_id": "call_read_progress",
            },
        ),
        (
            "tool_result",
            {
                "tool_name": "session_read_file",
                "success": True,
                "content": "成功读取 MEMORY_DEV_PROGRESS.md，包含 memory pipeline 进展。",
                "tool_call_id": "call_read_progress",
            },
        ),
        ("assistant_message", {"content": "已记录失败原因和成功重试结果。"}),
        ("run_finished", {"answer_length": 28, "tool_calls": 2}),
    ]
    _append_rows_with_filler(repo=repo, session_id=session_id, rows=rows, event_count=event_count)


def _append_forbidden_memory_events(*, repo: JsonlSessionRepository, session_id: str, event_count: int) -> None:
    rows: list[tuple[str, dict[str, Any]]] = [
        (
            "user_message",
            {"content": "临时暗号是蓝鲸，只用于当前调试，不要记住，也不要写入 memory。"},
        ),
        ("assistant_message", {"content": "明白，这只作为当前上下文，不会作为长期记忆。"}),
        ("user_message", {"content": "后续 daily 可以记录这次临时上下文，但 facts 不能出现临时暗号。"}),
        ("assistant_message", {"content": "会避免提升为 long-term fact。"}),
        ("run_finished", {"answer_length": 22, "tool_calls": 0}),
    ]
    _append_rows_with_filler(repo=repo, session_id=session_id, rows=rows, event_count=event_count)


def _append_rows_with_filler(
    *,
    repo: JsonlSessionRepository,
    session_id: str,
    rows: list[tuple[str, dict[str, Any]]],
    event_count: int,
) -> None:
    base_time = datetime(2026, 5, 1, 11, 0, tzinfo=UTC)
    output = list(rows)
    filler_index = 0
    while len(output) < event_count:
        insert_at = max(0, len(output) - 1)
        output.insert(
            insert_at,
            ("user_message", {"content": f"补充上下文 {filler_index}：继续观察 memory quality。"}),
        )
        filler_index += 1
    for index, (event_type, payload) in enumerate(output[:event_count]):
        _append_eval_event(
            repo=repo,
            session_id=session_id,
            event_id=f"evt_eval_{index:04d}",
            event_type=event_type,
            payload=payload,
            created_at=base_time + timedelta(seconds=index),
        )


def _append_eval_event(
    *,
    repo: JsonlSessionRepository,
    session_id: str,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    created_at: datetime,
    agent_id: str = "agent_main",
) -> None:
    repo.append_event(
        session_id,
        EventRecord(
            event_id=event_id,
            session_id=session_id,
            type=event_type,
            payload=payload,
            created_at=created_at,
            agent_id=agent_id,
            run_id=f"run_{session_id}",
            event_version=2,
        ),
    )


def _build_model_client(*, real_model: bool) -> ChatModelClient:
    if not real_model:
        return FixtureModelClient()
    settings = Settings.load()
    return OpenAICompatibleClient(
        base_url=settings.maintenance_llm_base_url or settings.llm_base_url,
        api_key=settings.maintenance_llm_api_key or settings.llm_api_key,
        model=settings.maintenance_llm_model or settings.llm_model,
        timeout_seconds=settings.maintenance_llm_timeout_seconds or settings.llm_timeout_seconds,
    )


def _build_mid_term_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    pack = _extract_mid_term_pack(messages)
    events = _pack_events(pack)
    event_ids = _event_ids(events)
    text = json.dumps(events, ensure_ascii=False)
    user_id = _first_event_id(events, "user_message") or event_ids[0]
    decision_id = _event_id_containing(events, "成对证据") or user_id
    has_name_context = any(name in text for name in ("小猪", "小明", "小王"))
    latest_name_value = "小王" if "小王" in text else "小明" if "小明" in text else ""
    latest_name_id = _event_id_containing(events, latest_name_value) if latest_name_value else None
    latest_name_id = latest_name_id or user_id
    goal_id = _event_id_containing(events, "daily 保真率") or user_id
    rolling_id = _event_id_containing(events, "rolling.md") or goal_id
    artifact_id = _event_id_containing(events, "MEMORY_DEV_PROGRESS.md") or goal_id
    tool_pair = _first_tool_pair(events)
    latest_pair = (
        _tool_pair_by_call_id(events, "call_latest_name")
        or _tool_pair_by_call_id(events, "call_final_name")
        or _tool_pair_by_call_id(events, "call_read_progress")
        or tool_pair
    )
    progress: list[dict[str, Any]] = []
    if tool_pair:
        progress.append(
            {
                "tool_name": "memory_search",
                "call_summary": "执行 memory_search 查询记忆或上下文。",
                "result_summary": "工具返回了与用户名字或 pipeline 相关的检索结果。",
                "success": True,
                "evidence_event_ids": [tool_pair[0], tool_pair[1]],
            }
        )
    if latest_pair and latest_pair != tool_pair:
        progress.append(
            {
                "tool_name": "memory_search",
                "call_summary": "查询关键最新状态。",
                "result_summary": (
                    f"查询结果确认最新名字是{latest_name_value}，或确认工具重试成功。"
                    if latest_name_value
                    else "查询结果确认关键状态或工具重试成功。"
                ),
                "success": True,
                "evidence_event_ids": [latest_pair[0], latest_pair[1]],
            }
        )
    active_context: list[dict[str, Any]] = []
    if "daily 保真率" in text:
        active_context.append(
            {
                "summary": "用户正在优先评估 memory pipeline 的 flush 速度、daily 保真率和 context compaction 关键内容保留率。",
                "evidence_event_ids": [goal_id],
                "confidence": 0.93,
            }
        )
    if has_name_context and latest_name_value:
        active_context.append(
            {
                "summary": f"用户最新名字是{latest_name_value}，旧称呼已被覆盖。",
                "evidence_event_ids": [latest_name_id],
                "confidence": 0.95,
            }
        )
    if "小猪" in text and "小明" in text and "小王" in text:
        active_context.append(
            {
                "summary": "用户名字经过纠正：小猪和小明均已作废，最新名字是小王。",
                "evidence_event_ids": [
                    _event_id_containing(events, "小猪") or user_id,
                    _event_id_containing(events, "小明") or latest_name_id,
                    latest_name_id,
                ],
                "confidence": 0.97,
            }
        )
    decisions: list[dict[str, Any]] = []
    if "成对证据" in text:
        decisions.append(
            {
                "summary": "mid-term flush 必须保持 tool_call 和 tool_result 成对证据。",
                "evidence_event_ids": [decision_id],
                "stability": "stable",
            }
        )
    open_questions: list[dict[str, Any]] = []
    if "rolling.md" in text:
        open_questions.append(
            {
                "question": "rolling.md 是否需要 daily 到 rolling 的后台归并器。",
                "evidence_event_ids": [rolling_id],
            }
        )
    candidates: list[dict[str, Any]] = []
    if has_name_context and latest_name_value:
        candidates.append(
            {
                "content": f"用户最新名字是{latest_name_value}。",
                "tags": ["preference", "long_term"],
                "confidence": 0.94,
                "why_reusable": "用户明确纠正称呼，后续跨会话可复用。",
                "evidence_event_ids": [latest_name_id],
            }
        )
    if "daily 保真率" in text:
        candidates.append(
            {
                "content": "用户优先关注 flush 速度、daily 保真率和 context compaction 关键内容保留率。",
                "tags": ["goal", "long_term"],
                "confidence": 0.88,
                "why_reusable": "这是当前 memory pipeline 优化阶段目标。",
                "evidence_event_ids": [goal_id],
            }
        )
    artifact_refs = (
        [
            {
                "path_or_file_id": "MEMORY_DEV_PROGRESS.md",
                "reason": "用户要求回溯开发进展文档。",
                "evidence_event_ids": [artifact_id],
            }
        ]
        if "MEMORY_DEV_PROGRESS.md" in text
        else []
    )
    if "文件系统" in text and "sqlite" in text:
        architecture_id = _event_id_containing(events, "文件系统") or user_id
        decisions.append(
            {
                "summary": "最终架构决策：memory 主存储使用文件系统，sqlite 暂不接入，后续最多作为派生 index。",
                "evidence_event_ids": [architecture_id],
                "stability": "stable",
            }
        )
        candidates.append(
            {
                "content": "memory 主存储使用文件系统，sqlite 暂不接入，后续最多作为派生 index。",
                "tags": ["architecture", "long_term"],
                "confidence": 0.92,
                "why_reusable": "这是 memory 存储架构决策。",
                "evidence_event_ids": [architecture_id],
            }
        )
    if "文件不存在" in text and "MEMORY_DEV_PROGRESS.md" in text:
        failure_id = _event_id_containing(events, "文件不存在") or user_id
        success_id = _event_id_containing(events, "MEMORY_DEV_PROGRESS.md") or failure_id
        missing_pair = _tool_pair_by_call_id(events, "call_missing") or _tool_pair_containing(events, "文件不存在")
        retry_pair = _tool_pair_by_call_id(events, "call_read_progress") or _tool_pair_containing(
            events,
            "MEMORY_DEV_PROGRESS.md",
        )
        progress_evidence = [failure_id, success_id]
        if missing_pair and retry_pair:
            progress_evidence = [missing_pair[0], missing_pair[1], retry_pair[0], retry_pair[1]]
        progress.append(
            {
                "tool_name": "session_read_file",
                "call_summary": "先读取 missing_config.md，随后改为读取 MEMORY_DEV_PROGRESS.md。",
                "result_summary": "第一次失败：文件不存在；第二次成功读取 MEMORY_DEV_PROGRESS.md。",
                "success": True,
                "evidence_event_ids": progress_evidence,
            }
        )
    if "临时暗号" in text and "不要记住" in text:
        secret_id = _event_id_containing(events, "临时暗号") or user_id
        active_context.append(
            {
                "summary": "临时暗号是蓝鲸，只用于当前调试；用户明确要求不要记住，不要写入 memory。",
                "evidence_event_ids": [secret_id],
                "confidence": 0.95,
            }
        )
        candidates = [
            item
            for item in candidates
            if "名字" not in str(item.get("content", "")) and "flush 速度" not in str(item.get("content", ""))
        ]
    return {
        "active_context": active_context,
        "decisions": decisions,
        "progress": progress,
        "open_questions": open_questions,
        "candidate_long_term": candidates,
        "artifact_refs": artifact_refs,
    }


def _build_compaction_summary(messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload = _extract_json_from_text(str(messages[-1].get("content", "")))
    units = [item for item in payload.get("compressed_units", []) if isinstance(item, dict)]
    events: list[dict[str, Any]] = []
    for unit in units:
        unit_events = unit.get("events")
        if isinstance(unit_events, list):
            events.extend(item for item in unit_events if isinstance(item, dict))
        else:
            events.extend(_events_from_slim_unit(unit, {}))
    event_ids = _event_ids(events)
    if not event_ids:
        event_ids = ["evt_missing"]
    text = json.dumps(events, ensure_ascii=False)
    has_name_context = any(name in text for name in ("小猪", "小明", "小王"))
    latest_name_value = "小王" if "小王" in text else "小明" if "小明" in text else ""
    latest_name_id = _event_id_containing(events, latest_name_value) if latest_name_value else None
    latest_name_id = latest_name_id or event_ids[0]
    goal_id = _event_id_containing(events, "daily 保真率") or event_ids[0]
    decision_id = _event_id_containing(events, "成对证据") or event_ids[0]
    rolling_id = _event_id_containing(events, "rolling.md") or goal_id
    tool_pair = _first_tool_pair(events)
    summary_parts: list[str] = []
    timeline: list[str] = []
    decisions: list[str] = []
    open_threads: list[str] = []
    memory_relevant: list[str] = []
    if has_name_context and latest_name_value:
        summary_parts.append(f"用户最新名字是{latest_name_value}。")
        timeline.append(f"用户先给出旧称呼，之后明确改为{latest_name_value}。")
        memory_relevant.append(f"用户最新名字是{latest_name_value}。")
    if "daily 保真率" in text:
        summary_parts.append("当前重点是验证 flush 速度、daily 保真率、context compaction 关键内容保留率。")
        timeline.append("用户把评估 flush/daily/compaction 质量作为产品化前置条件。")
        memory_relevant.append("用户关注 flush 速度、daily 保真率和 context compaction 关键内容保留率。")
    if "成对证据" in text:
        summary_parts.append("mid-term flush 需要保留 tool_call 和 tool_result 成对证据。")
        decisions.append("mid-term flush 必须保持 tool_call 和 tool_result 成对证据。")
    if "rolling.md" in text:
        summary_parts.append("rolling.md 是否需要 daily 到 rolling 的后台归并器仍是开放问题。")
        open_threads.append("rolling.md 是否需要 daily 到 rolling 的后台归并器。")
    if "MEMORY_DEV_PROGRESS.md" in text:
        summary_parts.append("相关文档包括 MEMORY_DEV_PROGRESS.md。")
    if "小猪" in text and "小明" in text and "小王" in text:
        summary_parts.insert(1, "用户名字经过纠正：小猪和小明均已作废，最新名字是小王。")
        timeline[0] = "用户先说名字叫小猪，随后改为小明，最终确认小王才是最新名字。"
    if "文件系统" in text and "sqlite" in text:
        summary_parts.append("最终架构决策：memory 主存储使用文件系统，sqlite 暂不接入，后续最多作为派生 index。")
        decisions.append("memory 主存储使用文件系统，sqlite 暂不接入，后续最多作为派生 index。")
        memory_relevant.append("memory 主存储使用文件系统，sqlite 暂不接入，后续最多作为派生 index。")
    if "文件不存在" in text and "MEMORY_DEV_PROGRESS.md" in text:
        summary_parts.append("工具调用先失败：文件不存在；随后成功读取 MEMORY_DEV_PROGRESS.md。")
    tool_progress: list[dict[str, Any]] = []
    if tool_pair:
        tool_progress.append(
            {
                "tool_name": "memory_search",
                "call_summary": "查询用户名字或 pipeline 上下文。",
                "result_summary": (
                    f"工具结果用于确认最新名字是{latest_name_value}或补充 pipeline 背景。"
                    if latest_name_value
                    else "工具结果用于补充 pipeline 背景。"
                ),
                "success": True,
                "evidence_event_ids": [tool_pair[0], tool_pair[1]],
            }
        )
    retry_pair = _tool_pair_by_call_id(events, "call_read_progress") or _tool_pair_containing(
        events,
        "MEMORY_DEV_PROGRESS.md",
    )
    if retry_pair:
        tool_progress.append(
            {
                "tool_name": "session_read_file",
                "call_summary": "读取 MEMORY_DEV_PROGRESS.md。",
                "result_summary": "工具结果显示成功读取 MEMORY_DEV_PROGRESS.md。",
                "success": True,
                "evidence_event_ids": [retry_pair[0], retry_pair[1]],
            }
        )
    if "临时暗号" in text and "不要记住" in text:
        summary_parts.append("临时暗号是蓝鲸，只用于当前调试；用户明确要求不要记住，不要写入 memory。")
    evidence_ids = sorted(
        {
            event_id
            for event_id in [
                latest_name_id if has_name_context else None,
                goal_id if "daily 保真率" in text else None,
                decision_id if "成对证据" in text else None,
                rolling_id if "rolling.md" in text else None,
            ]
            if event_id
        }
    )
    if not evidence_ids:
        evidence_ids = [event_ids[0]]
    return {
        "summary": "历史上下文：" + "；".join(summary_parts),
        "timeline": timeline,
        "decisions": decisions,
        "open_threads": open_threads,
        "tool_progress": tool_progress,
        "agent_activity": ["agent 持续整理 memory pipeline 评测上下文。"],
        "memory_relevant": memory_relevant,
        "evidence_event_ids": evidence_ids,
    }


def _coverage(text: str, items: list[CriticalItem]) -> tuple[float, list[str]]:
    if not items:
        return 1.0, []
    missing: list[str] = []
    for item in items:
        if not all(keyword in text for keyword in item.keywords):
            missing.append(item.label)
    covered = len(items) - len(missing)
    return covered / len(items), missing


def _invalid_evidence_count(text: str, valid_event_ids: set[str]) -> int:
    count = 0
    for raw in re.findall(r"\[evidence=([^\]]*)\]", text):
        for event_id in raw.split(","):
            normalized = event_id.strip()
            if normalized and normalized not in valid_event_ids:
                count += 1
    return count


def _read_agent_facts_text(root_dir: Path, agent_id: str) -> str:
    facts_path = root_dir / "agents" / agent_id / "facts.jsonl"
    if not facts_path.exists():
        return ""
    return facts_path.read_text(encoding="utf-8")


def _retained_tool_pair(
    events: list[EventRecord],
    tool_call_id: str | None,
    *,
    original_events: list[EventRecord] | None = None,
) -> bool:
    if tool_call_id is None:
        return True
    call_seen = False
    result_seen = False
    for event in events:
        if event.type == "tool_call" and event.payload.get("tool_call_id") == tool_call_id:
            call_seen = True
        if event.type == "tool_result" and event.payload.get("tool_call_id") == tool_call_id:
            result_seen = True
    if call_seen and result_seen:
        return True
    if original_events is None:
        return False
    expected_event_ids = {
        event.event_id
        for event in original_events
        if event.type in {"tool_call", "tool_result"} and event.payload.get("tool_call_id") == tool_call_id
    }
    if len(expected_event_ids) < 2:
        return False
    for event in events:
        if event.type != "context_summary":
            continue
        structured = event.payload.get("structured")
        if not isinstance(structured, dict):
            continue
        tool_progress = structured.get("tool_progress")
        if not isinstance(tool_progress, list):
            continue
        for item in tool_progress:
            if not isinstance(item, dict):
                continue
            evidence = item.get("evidence_event_ids")
            if isinstance(evidence, list) and expected_event_ids.issubset({str(value) for value in evidence}):
                return True
    return False


def _build_summary(reports: list[CaseReport]) -> dict[str, Any]:
    if not reports:
        return {}
    return {
        "case_count": len(reports),
        "avg_flush_total_ms": round(mean(item.flush_total_ms for item in reports), 2),
        "max_flush_total_ms": round(max(item.flush_total_ms for item in reports), 2),
        "avg_compaction_total_ms": round(mean(item.compaction_total_ms for item in reports), 2),
        "min_daily_coverage": min(item.daily_coverage for item in reports),
        "min_facts_coverage": min(item.facts_coverage for item in reports),
        "min_compaction_coverage": min(
            item.compaction_coverage for item in reports if item.compaction_reason != "skipped"
        )
        if any(item.compaction_reason != "skipped" for item in reports)
        else 0.0,
        "total_invalid_evidence": sum(item.daily_invalid_evidence_count for item in reports),
        "retained_latest_tool_pair_all": all(item.retained_latest_tool_pair for item in reports),
        "hallucination_terms": sorted({term for item in reports for term in item.hallucination_terms}),
        "forbidden_fact_terms": sorted({term for item in reports for term in item.forbidden_fact_terms}),
    }


def _print_case_summary(report: CaseReport) -> None:
    print(
        "case "
        f"scenario={report.case_name} events={report.event_count} mode={report.mode} packs={report.pack_count} "
        f"pack_ms={report.pack_build_ms:.1f} flush_ms={report.flush_total_ms:.1f} "
        f"compact_ms={report.compaction_total_ms:.1f} daily_cov={report.daily_coverage:.2f} "
        f"facts_cov={report.facts_coverage:.2f} compact_cov={report.compaction_coverage:.2f} "
        f"invalid_evidence={report.daily_invalid_evidence_count} "
        f"retained_latest_tool_pair={report.retained_latest_tool_pair}"
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate memory flush and context compaction quality.")
    parser.add_argument(
        "--preset",
        choices=["custom", *sorted(EVAL_PRESETS)],
        default="custom",
        help="Use a maintained evaluation preset. Presets override scenarios/events/model mode.",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        default=["baseline"],
        help=f"Scenarios to evaluate. Use 'all' for all. Available: {', '.join(sorted(SCENARIOS))}.",
    )
    parser.add_argument("--events", nargs="+", type=int, default=[50, 120, 300], help="Event counts to evaluate.")
    parser.add_argument("--real-model", action="store_true", help="Use .env OpenAI-compatible model instead of fixture.")
    parser.add_argument("--keep-data", action="store_true", help="Keep generated temporary data directories.")
    parser.add_argument("--skip-compaction", action="store_true", help="Evaluate flush only.")
    parser.add_argument("--max-input-tokens", type=int, default=5200, help="Max input tokens for mid-term pack batches.")
    parser.add_argument(
        "--model-context-window-tokens",
        type=int,
        default=32768,
        help="Context window used to calculate mid-term pack input budget.",
    )
    parser.add_argument(
        "--model-input-ratio",
        type=float,
        default=0.35,
        help="Context window ratio available for mid-term pack input.",
    )
    parser.add_argument("--output-dir", default=None, help="Parent directory for generated case data.")
    parser.add_argument("--report", default=None, help="JSON report output path.")
    parser.add_argument("--quality-gate", action="store_true", help="Exit non-zero when quality metrics miss thresholds.")
    parser.add_argument("--min-coverage", type=float, default=1.0, help="Minimum daily/facts/compaction coverage.")
    return parser.parse_args()


def _apply_preset(args: argparse.Namespace) -> argparse.Namespace:
    if args.preset == "custom":
        return args
    preset = EVAL_PRESETS[args.preset]
    args.scenarios = list(preset.scenarios)
    args.events = list(preset.events)
    args.real_model = preset.real_model
    args.quality_gate = preset.quality_gate
    return args


def _quality_gate_failures(
    *,
    reports: list[CaseReport],
    summary: dict[str, Any],
    min_coverage: float,
    skip_compaction: bool,
) -> list[str]:
    failures: list[str] = []
    if not reports:
        return ["no reports produced"]
    if summary.get("min_daily_coverage", 0.0) < min_coverage:
        failures.append(f"min_daily_coverage < {min_coverage}")
    if summary.get("min_facts_coverage", 0.0) < min_coverage:
        failures.append(f"min_facts_coverage < {min_coverage}")
    if not skip_compaction and summary.get("min_compaction_coverage", 0.0) < min_coverage:
        failures.append(f"min_compaction_coverage < {min_coverage}")
    if summary.get("total_invalid_evidence", 0) != 0:
        failures.append("daily contains invalid evidence ids")
    if summary.get("retained_latest_tool_pair_all") is not True:
        failures.append("latest tool_call/tool_result pair was not retained or summarized")
    if summary.get("hallucination_terms"):
        failures.append(f"hallucination terms present: {summary['hallucination_terms']}")
    if summary.get("forbidden_fact_terms"):
        failures.append(f"forbidden fact terms present: {summary['forbidden_fact_terms']}")
    return failures


def _select_scenarios(raw_names: list[str]) -> list[EvalScenario]:
    names = list(raw_names)
    if "all" in names:
        names = sorted(SCENARIOS)
    scenarios: list[EvalScenario] = []
    for name in names:
        if name not in SCENARIOS:
            raise ValueError(f"unknown scenario: {name}")
        scenarios.append(SCENARIOS[name])
    return scenarios


def _make_data_dir(*, root_dir: Path | None, event_count: int, scenario_name: str) -> Path:
    if root_dir is not None:
        path = root_dir / f"memory_pipeline_eval_{scenario_name}_{event_count}_{int(time.time() * 1000)}"
        path.mkdir(parents=True, exist_ok=False)
        return path
    return Path(tempfile.mkdtemp(prefix=f"memory_pipeline_eval_{scenario_name}_{event_count}_"))


def _context(session_id: str) -> RunContext:
    return RunContext(
        session_id=session_id,
        run_id=f"run_{session_id}",
        agent_id="agent_main",
        turn_id=f"turn_{session_id}",
        entry_agent_id="agent_main",
        parent_run_id=None,
        trace_flags={},
    )


def _classify_model_call(system_prompt: str) -> str:
    if "mid-term memory distillation" in system_prompt:
        return "mid_term_summary"
    if "session context compactor" in system_prompt:
        return "context_compaction"
    return "unknown"


def _extract_mid_term_pack(messages: list[dict[str, Any]]) -> dict[str, Any]:
    if not messages:
        return {}
    content = str(messages[-1].get("content", ""))
    marker = "Event pack:\n"
    index = content.find(marker)
    if index < 0:
        return {}
    return json.loads(content[index + len(marker) :].strip())


def _extract_json_from_text(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        return {}
    payload = json.loads(text[start:])
    return payload if isinstance(payload, dict) else {}


def _pack_events(pack: dict[str, Any]) -> list[dict[str, Any]]:
    event_index = _pack_event_index(pack)
    event_type_by_id = {
        str(item.get("event_id", "")).strip(): str(item.get("type", "")).strip()
        for item in event_index
        if str(item.get("event_id", "")).strip()
    }
    detailed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in pack.get("semantic_units", []):
        if not isinstance(unit, dict):
            continue
        unit_events = unit.get("events")
        if isinstance(unit_events, list):
            for event in unit_events:
                if not isinstance(event, dict):
                    continue
                event_id = str(event.get("event_id", "")).strip()
                if event_id and event_id in seen:
                    continue
                if event_id:
                    seen.add(event_id)
                detailed.append(event)
            continue

        for event in _events_from_slim_unit(unit, event_type_by_id):
            event_id = str(event.get("event_id", "")).strip()
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            detailed.append(event)
    if detailed:
        return detailed

    raw = event_index
    if not raw:
        raw = pack.get("events")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _pack_event_index(pack: dict[str, Any]) -> list[dict[str, Any]]:
    raw = pack.get("event_index")
    if raw is None:
        raw = pack.get("events")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _events_from_slim_unit(unit: dict[str, Any], event_type_by_id: dict[str, str]) -> list[dict[str, Any]]:
    event_ids = [str(item).strip() for item in unit.get("event_ids", []) if isinstance(item, str) and item.strip()]
    if not event_ids:
        return []
    unit_type = str(unit.get("unit_type", "")).strip()
    summary = unit.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    if unit_type == "tool_pair" and len(event_ids) >= 2:
        call_id = f"synthetic_{event_ids[0]}_{event_ids[1]}"
        return [
            {
                "event_id": event_ids[0],
                "type": "tool_call",
                "tool_call_id": call_id,
                "summary": summary,
                "payload": {
                    "tool_call_id": call_id,
                    "name": summary.get("tool_name"),
                    "arguments": summary.get("call_arguments"),
                },
            },
            {
                "event_id": event_ids[1],
                "type": "tool_result",
                "tool_call_id": call_id,
                "summary": summary,
                "payload": {
                    "tool_call_id": call_id,
                    "tool_name": summary.get("tool_name"),
                    "success": summary.get("result_success"),
                    "content": summary.get("result_content"),
                },
            },
        ]
    return [
        {
            "event_id": event_id,
            "type": event_type_by_id.get(event_id, "event"),
            "summary": summary,
        }
        for event_id in event_ids
    ]


def _event_ids(events: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("event_id", "")).strip() for item in events if str(item.get("event_id", "")).strip()]


def _first_event_id(events: list[dict[str, Any]], event_type: str) -> str | None:
    for event in events:
        if event.get("type") == event_type:
            event_id = str(event.get("event_id", "")).strip()
            if event_id:
                return event_id
    return None


def _event_id_containing(events: list[dict[str, Any]], keyword: str) -> str | None:
    for event in events:
        if keyword in json.dumps(event, ensure_ascii=False):
            event_id = str(event.get("event_id", "")).strip()
            if event_id:
                return event_id
    return None


def _first_tool_pair(events: list[dict[str, Any]]) -> tuple[str, str] | None:
    calls: dict[str, str] = {}
    for event in events:
        call_id = _event_tool_call_id(event)
        event_id = str(event.get("event_id", "")).strip()
        if not call_id or not event_id:
            continue
        if event.get("type") == "tool_call":
            calls[call_id] = event_id
        elif event.get("type") == "tool_result" and call_id in calls:
            return calls[call_id], event_id
    return None


def _tool_pair_by_call_id(events: list[dict[str, Any]], target_call_id: str) -> tuple[str, str] | None:
    call_event_id: str | None = None
    result_event_id: str | None = None
    for event in events:
        if _event_tool_call_id(event) != target_call_id:
            continue
        event_id = str(event.get("event_id", "")).strip()
        if event.get("type") == "tool_call":
            call_event_id = event_id
        if event.get("type") == "tool_result":
            result_event_id = event_id
    if call_event_id and result_event_id:
        return call_event_id, result_event_id
    return None


def _tool_pair_containing(events: list[dict[str, Any]], keyword: str) -> tuple[str, str] | None:
    calls: dict[str, str] = {}
    for event in events:
        call_id = _event_tool_call_id(event)
        event_id = str(event.get("event_id", "")).strip()
        if not call_id or not event_id:
            continue
        event_text = json.dumps(event, ensure_ascii=False)
        if event.get("type") == "tool_call":
            calls[call_id] = event_id
            continue
        if event.get("type") == "tool_result" and call_id in calls and keyword in event_text:
            return calls[call_id], event_id
    return None


def _event_tool_call_id(event: dict[str, Any]) -> str:
    raw = event.get("tool_call_id")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    payload = event.get("payload")
    if isinstance(payload, dict):
        raw_payload = payload.get("tool_call_id")
        if isinstance(raw_payload, str) and raw_payload.strip():
            return raw_payload.strip()
    return ""


def _events_to_text(events: list[EventRecord]) -> str:
    return "\n".join(json.dumps(event.payload, ensure_ascii=False) for event in events)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
