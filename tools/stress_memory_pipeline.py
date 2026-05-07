"""Practical stress test for chat/memory/flush/compaction pipeline.

Run:
  uv run python tools/stress_memory_pipeline.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.domain.models import RunContext, ToolCall
from app.domain.protocols import ModelResponse, StreamChunk
from app.infra.locks.session_lock_manager import SessionLockManager
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.context_assembler import ContextAssembler
from app.runtime.context_compactor import ContextCompactionConfig, ContextCompactor
from app.runtime.event_recorder import EventRecorder
from app.runtime.mid_term_flusher import MidTermFlusher
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.schemas.chat import ChatRequest
from app.services.chat_service import ChatService
from app.services.session_title_service import SessionTitleService
from app.state.manager import StateManager
from app.state.stores.jsonl_file_store import JsonlFileStateStore
from app.tools.builtins import (
    MemoryForgetTool,
    MemoryInspectTool,
    MemorySearchTool,
    MemoryUpdateTool,
    MemoryWriteTool,
    StateListTool,
    StatePublishTool,
    StateSetTool,
)
from app.tools.registry import ToolRegistry


@dataclass(slots=True)
class LoadResult:
    name: str
    concurrency: int
    total_requests: int
    success_count: int
    fail_count: int
    throughput_rps: float
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


@dataclass(slots=True)
class ThresholdSummary:
    baseline_p95_ms: float
    latency_cliff_concurrency: int | None
    fail_cliff_concurrency: int | None
    saturation_concurrency: int | None


class StressModelClient:
    """Model stub for runtime + mid-term flush + compaction prompts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tool_call_index = 0

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> ModelResponse:
        _ = system_prompt
        prompt = str(messages[-1].get("content", "")) if messages else ""
        if "Event pack:\n" in prompt:
            return ModelResponse(content=json.dumps(self._build_mid_term_payload(prompt), ensure_ascii=False), tool_calls=[])
        if "Compress these old session events into one structured context summary." in prompt:
            return ModelResponse(content=json.dumps(self._build_compaction_payload(prompt), ensure_ascii=False), tool_calls=[])
        if self._has_tool_result(messages):
            return ModelResponse(content="收到，已处理并记录。", tool_calls=[])
        if tools:
            return ModelResponse(
                content="",
                tool_calls=[
                    ToolCall(
                        name="memory_write",
                        arguments={"content": "用户指定称呼为哈喽", "tags": ["preference", "long_term", "name"]},
                        tool_call_id=self._next_tool_call_id("write"),
                    ),
                    ToolCall(
                        name="memory_search",
                        arguments={"query": "名字", "limit": 5},
                        tool_call_id=self._next_tool_call_id("search"),
                    ),
                ],
            )
        return ModelResponse(content="收到。", tool_calls=[])

    async def generate_stream(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Any:
        response = self.generate(system_prompt=system_prompt, messages=messages, tools=tools)
        if response.content:
            yield StreamChunk(delta=response.content, finished=False, has_tool_call_delta=False)
        yield StreamChunk(delta="", tool_calls=response.tool_calls, finished=True, has_tool_call_delta=bool(response.tool_calls))

    def _next_tool_call_id(self, prefix: str) -> str:
        with self._lock:
            self._tool_call_index += 1
            return f"call_{prefix}_{self._tool_call_index}"

    @staticmethod
    def _has_tool_result(messages: list[dict[str, Any]]) -> bool:
        return any(str(message.get("role", "")).strip().lower() == "tool" for message in messages)

    @staticmethod
    def _parse_json_from_marker(text: str, marker: str) -> dict[str, Any]:
        index = text.find(marker)
        if index < 0:
            return {}
        raw = text[index + len(marker) :].strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _first_by_type(events: list[dict[str, Any]], event_type: str) -> str | None:
        for row in events:
            if str(row.get("type", "")).strip() == event_type:
                event_id = str(row.get("event_id", "")).strip()
                if event_id:
                    return event_id
        return None

    def _build_mid_term_payload(self, prompt: str) -> dict[str, Any]:
        pack = self._parse_json_from_marker(prompt, "Event pack:\n")
        raw_events = pack.get("events")
        if not isinstance(raw_events, list):
            raw_events = pack.get("event_index")
        events = [row for row in raw_events if isinstance(row, dict)] if isinstance(raw_events, list) else []
        event_ids = [str(row.get("event_id", "")).strip() for row in events if str(row.get("event_id", "")).strip()] or ["evt_missing"]
        user_event = self._first_by_type(events, "user_message") or event_ids[0]
        assistant_event = self._first_by_type(events, "assistant_message") or event_ids[-1]
        call_event, result_event = self._first_tool_pair_from_pack(pack)
        call_event = call_event or self._first_by_type(events, "tool_call") or event_ids[0]
        result_event = result_event or self._first_by_type(events, "tool_result") or event_ids[-1]
        finish_event = self._first_by_type(events, "run_finished") or event_ids[-1]
        return {
            "active_context": [{"summary": "用户要求系统记忆一致", "evidence_event_ids": [user_event], "confidence": 0.82}],
            "decisions": [{"summary": "完成记忆写入并检索确认", "evidence_event_ids": [assistant_event], "stability": "tentative"}],
            "progress": [
                {
                    "tool_name": "memory_search",
                    "call_summary": "查询名字相关记忆",
                    "result_summary": "命中称呼记录",
                    "success": True,
                    "evidence_event_ids": [call_event, result_event],
                }
            ],
            "open_questions": [{"question": "是否提升到 shared", "evidence_event_ids": [finish_event]}],
            "candidate_long_term": [
                {
                    "content": "用户偏好系统记住其称呼并保持一致。",
                    "tags": ["preference", "long_term", "name"],
                    "confidence": 0.86,
                    "why_reusable": "跨会话复用",
                    "evidence_event_ids": [user_event],
                }
            ],
            "artifact_refs": [{"path_or_artifact_id": "session://events", "reason": "追溯执行", "evidence_event_ids": [finish_event]}],
        }

    @staticmethod
    def _first_tool_pair_from_pack(pack: dict[str, Any]) -> tuple[str | None, str | None]:
        raw_units = pack.get("semantic_units")
        if not isinstance(raw_units, list):
            return (None, None)
        for unit in raw_units:
            if not isinstance(unit, dict):
                continue
            if str(unit.get("unit_type", "")).strip() != "tool_pair":
                continue
            event_ids = unit.get("event_ids")
            if not isinstance(event_ids, list) or len(event_ids) < 2:
                continue
            call_event = str(event_ids[0]).strip() if isinstance(event_ids[0], str) else ""
            result_event = str(event_ids[1]).strip() if isinstance(event_ids[1], str) else ""
            if call_event and result_event:
                return (call_event, result_event)
        return (None, None)

    def _build_compaction_payload(self, prompt: str) -> dict[str, Any]:
        start = prompt.find("{")
        payload: dict[str, Any] = {}
        if start >= 0:
            try:
                parsed = json.loads(prompt[start:])
                if isinstance(parsed, dict):
                    payload = parsed
            except json.JSONDecodeError:
                payload = {}
        evidence: list[str] = []
        for unit in payload.get("compressed_units", []):
            if not isinstance(unit, dict):
                continue
            for event_id in unit.get("event_ids", []):
                normalized = str(event_id).strip()
                if normalized and normalized not in evidence:
                    evidence.append(normalized)
            if len(evidence) >= 24:
                break
        if not evidence:
            evidence = ["evt_missing"]
        return {
            "summary": "历史事件已压缩，保留用户意图与工具进展。",
            "timeline": ["用户提问", "调用工具", "得到结果"],
            "decisions": ["保留最近事件原文，其余转摘要"],
            "open_threads": ["后续是否共享该偏好"],
            "tool_progress": [
                {
                    "tool_name": "memory_search",
                    "call_summary": "查询记忆",
                    "result_summary": "返回偏好",
                    "success": True,
                    "evidence_event_ids": evidence[:2] if len(evidence) >= 2 else evidence,
                }
            ],
            "agent_activity": ["agent_main 编排并维护记忆"],
            "memory_relevant": ["称呼偏好是长期可复用事实"],
            "evidence_event_ids": evidence,
        }


def build_chat_stack(
    data_dir: Path,
    *,
    enable_flush: bool,
    enable_compaction: bool,
) -> tuple[ChatService, MemoryManager, JsonlSessionRepository, MidTermFlusher | None]:
    session_repository = JsonlSessionRepository(data_dir=data_dir)
    state_store = JsonlFileStateStore(root_dir=data_dir / "state")
    state_manager = StateManager(store=state_store)
    capability_registry = AgentCapabilityRegistry.for_tests()
    memory_store = FileMemoryStore(root_dir=data_dir / "memory")
    memory_manager = MemoryManager(capability_registry=capability_registry, memory_store=memory_store)
    skill_repository = MarkdownSkillRepository(skills_dir=Path("app/skills"))
    agent_document_repository = MarkdownAgentDocumentRepository(agents_dir=Path("app/agents"))
    model_client = StressModelClient()

    tool_registry = ToolRegistry(capability_registry=capability_registry)
    tool_registry.register(MemoryWriteTool(memory_manager=memory_manager))
    tool_registry.register(MemorySearchTool(memory_manager=memory_manager))
    tool_registry.register(MemoryInspectTool(memory_manager=memory_manager))
    tool_registry.register(MemoryForgetTool(memory_manager=memory_manager))
    tool_registry.register(MemoryUpdateTool(memory_manager=memory_manager))
    tool_registry.register(StateSetTool(state_manager=state_manager))
    tool_registry.register(StatePublishTool(state_manager=state_manager))
    tool_registry.register(StateListTool(state_manager=state_manager))

    session_manager = SessionManager(session_repository=session_repository)
    session_lock_manager = SessionLockManager()
    event_recorder = EventRecorder(session_repository=session_repository)
    context_assembler = ContextAssembler(
        session_repository=session_repository,
        skill_repository=skill_repository,
        agent_document_repository=agent_document_repository,
        memory_manager=memory_manager,
        state_manager=state_manager,
        tool_executor=tool_registry,
    )
    flusher = (
        MidTermFlusher(session_repository=session_repository, memory_store=memory_store, model_client=model_client)
        if enable_flush
        else None
    )
    compactor = (
        ContextCompactor(
            session_repository=session_repository,
            model_client=model_client,
            config=ContextCompactionConfig(
                enabled=True,
                trigger_event_count=60,
                trigger_token_count=12000,
                trigger_context_window_ratio=0.45,
                retain_event_count=32,
                retain_token_count=7000,
            ),
        )
        if enable_compaction
        else None
    )
    runtime = AgentRuntime(
        session_manager=session_manager,
        event_recorder=event_recorder,
        context_assembler=context_assembler,
        model_client=model_client,
        tool_executor=tool_registry,
        mid_term_flusher=flusher,
        context_compactor=compactor,
    )
    service = ChatService(
        runtime=runtime,
        session_manager=session_manager,
        session_repository=session_repository,
        capability_registry=capability_registry,
        session_lock_manager=session_lock_manager,
        session_title_service=SessionTitleService(model_client=model_client),
    )
    return service, memory_manager, session_repository, flusher


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if q <= 0:
        return ordered[0]
    if q >= 100:
        return ordered[-1]
    pos = (len(ordered) - 1) * (q / 100.0)
    low = int(pos)
    high = min(low + 1, len(ordered) - 1)
    weight = pos - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


async def run_chat_load(
    *,
    service: ChatService,
    scenario_name: str,
    concurrency: int,
    total_requests: int,
    same_session: bool,
    skill_names: list[str],
) -> LoadResult:
    latencies_ms: list[float] = []
    success = 0
    fail = 0
    lock = asyncio.Lock()
    idx = 0

    async def worker(worker_id: int) -> None:
        nonlocal idx, success, fail
        while True:
            async with lock:
                if idx >= total_requests:
                    return
                current = idx
                idx += 1
            session_id = (
                f"sess_stress_shared_{scenario_name}"
                if same_session
                else f"sess_stress_{scenario_name}_{worker_id}_{current}"
            )
            req = ChatRequest(
                session_id=session_id,
                message=f"压力消息 {current}",
                skill_names=skill_names,
                max_tool_rounds=3,
            )
            started = time.perf_counter()
            try:
                await service.chat(req)
                success += 1
            except Exception:
                fail += 1
            finally:
                latencies_ms.append((time.perf_counter() - started) * 1000.0)

    started = time.perf_counter()
    tasks = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    await asyncio.gather(*tasks)
    await service.wait_for_background_tasks()
    elapsed = max(1e-9, time.perf_counter() - started)
    return LoadResult(
        name=scenario_name,
        concurrency=concurrency,
        total_requests=total_requests,
        success_count=success,
        fail_count=fail,
        throughput_rps=success / elapsed,
        mean_ms=statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        p50_ms=percentile(latencies_ms, 50.0),
        p95_ms=percentile(latencies_ms, 95.0),
        p99_ms=percentile(latencies_ms, 99.0),
        max_ms=max(latencies_ms) if latencies_ms else 0.0,
    )


def summarize_threshold(results: list[LoadResult]) -> ThresholdSummary:
    ordered = sorted(results, key=lambda x: x.concurrency)
    baseline_p95 = ordered[0].p95_ms if ordered else 0.0
    latency_cliff = None
    fail_cliff = None
    saturation = None
    for i, row in enumerate(ordered):
        fail_rate = row.fail_count / max(1, row.total_requests)
        if fail_cliff is None and fail_rate > 0.01:
            fail_cliff = row.concurrency
        if latency_cliff is None and baseline_p95 > 0 and row.p95_ms >= baseline_p95 * 3.0:
            latency_cliff = row.concurrency
        if i > 0 and saturation is None:
            prev = ordered[i - 1]
            if prev.throughput_rps > 0:
                growth = (row.throughput_rps - prev.throughput_rps) / prev.throughput_rps
                if growth < 0.10 and row.p95_ms >= baseline_p95 * 1.8:
                    saturation = row.concurrency
    return ThresholdSummary(
        baseline_p95_ms=baseline_p95,
        latency_cliff_concurrency=latency_cliff,
        fail_cliff_concurrency=fail_cliff,
        saturation_concurrency=saturation,
    )


def print_result_table(title: str, results: list[LoadResult]) -> None:
    print()
    print(f"=== {title} ===")
    print("{:>5} {:>6} {:>6} {:>6} {:>8} {:>9} {:>9} {:>9} {:>9} {:>9}".format(
        "conc", "total", "ok", "fail", "RPS", "mean_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"
    ))
    for item in sorted(results, key=lambda x: x.concurrency):
        print("{:>5} {:>6} {:>6} {:>6} {:>8.2f} {:>9.2f} {:>9.2f} {:>9.2f} {:>9.2f} {:>9.2f}".format(
            item.concurrency,
            item.total_requests,
            item.success_count,
            item.fail_count,
            item.throughput_rps,
            item.mean_ms,
            item.p50_ms,
            item.p95_ms,
            item.p99_ms,
            item.max_ms,
        ))


def print_threshold(label: str, summary: ThresholdSummary) -> None:
    print(
        f"[{label}] baseline_p95={summary.baseline_p95_ms:.2f}ms, "
        f"saturation_conc={summary.saturation_concurrency}, "
        f"latency_cliff_conc={summary.latency_cliff_concurrency}, "
        f"fail_cliff_conc={summary.fail_cliff_concurrency}"
    )


def inspect_mid_term_files(data_dir: Path) -> dict[str, int]:
    base = data_dir / "memory" / "agents" / "agent_main" / "mid_term"
    json_files = list(base.rglob("*.json"))
    invalid_json_files = 0
    total_json_files = 0
    for path in json_files:
        total_json_files += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                invalid_json_files += 1
        except Exception:
            invalid_json_files += 1
    tmp_files = _settled_tmp_file_count(base)
    return {
        "mid_term_json_files": total_json_files,
        "mid_term_invalid_json_files": invalid_json_files,
        "mid_term_tmp_files": tmp_files,
    }


def _settled_tmp_file_count(base: Path) -> int:
    """Avoid flagging atomic-write temp files that disappear immediately after replace()."""
    tmp_files: list[Path] = []
    for _ in range(5):
        tmp_files = list(base.rglob("*.tmp"))
        if not tmp_files:
            return 0
        time.sleep(0.05)
    return len(tmp_files)


async def run_memory_write_consistency_stress(
    *,
    memory_manager: MemoryManager,
    data_dir: Path,
    total_writes: int,
    concurrency: int,
) -> dict[str, Any]:
    ctx = RunContext(
        session_id="sess_memory_write_stress",
        run_id="run_memory_write_stress",
        agent_id="agent_main",
        turn_id="turn_memory_write_stress",
        entry_agent_id="agent_main",
    )
    facts_path = data_dir / "memory" / "agents" / "agent_main" / "facts.jsonl"
    before = len([line for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]) if facts_path.exists() else 0
    success = 0
    fail = 0
    latencies_ms: list[float] = []
    idx = 0
    lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal idx, success, fail
        while True:
            async with lock:
                if idx >= total_writes:
                    return
                current = idx
                idx += 1
            started = time.perf_counter()
            try:
                await asyncio.to_thread(
                    memory_manager.write_memory_with_result,
                    f"并发写入偏好_{current}_{uuid4().hex[:8]}",
                    ["preference", "long_term", "stress"],
                    ctx,
                    f"evt_stress_{current}",
                    "stress_memory_write",
                    None,
                )
                success += 1
            except Exception:
                fail += 1
            finally:
                latencies_ms.append((time.perf_counter() - started) * 1000.0)

    started_all = time.perf_counter()
    tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
    await asyncio.gather(*tasks)
    elapsed = max(1e-9, time.perf_counter() - started_all)

    lines = [line for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()] if facts_path.exists() else []
    parse_fail = 0
    for line in lines:
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                parse_fail += 1
        except json.JSONDecodeError:
            parse_fail += 1
    after = len(lines)
    return {
        "scenario": "memory_write_consistency",
        "concurrency": concurrency,
        "total_writes": total_writes,
        "success": success,
        "fail": fail,
        "throughput_rps": success / elapsed,
        "mean_ms": statistics.fmean(latencies_ms) if latencies_ms else 0.0,
        "p95_ms": percentile(latencies_ms, 95.0),
        "facts_before_lines": before,
        "facts_after_lines": after,
        "facts_added_lines": max(0, after - before),
        "facts_parse_fail": parse_fail,
    }


async def run_maintenance_race_sweep() -> list[dict[str, Any]]:
    root = Path("data/stress_bench_maintenance_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    for conc in [1, 2, 4, 6, 8, 10, 12]:
        data_dir = root / f"conc_{conc}"
        service, _, _, flusher = build_chat_stack(data_dir, enable_flush=True, enable_compaction=True)
        assert flusher is not None
        run = await run_chat_load(
            service=service,
            scenario_name=f"maintenance_same_{conc}",
            concurrency=conc,
            total_requests=max(36, conc * 8),
            same_session=True,
            skill_names=["base", "memory", "tools"],
        )
        integrity = inspect_mid_term_files(data_dir)
        metrics = flusher.collect_job_metrics()
        results.append(
            {
                "concurrency": conc,
                "requests": run.total_requests,
                "fail_count": run.fail_count,
                "p95_ms": round(run.p95_ms, 2),
                "throughput_rps": round(run.throughput_rps, 2),
                "flush_retry_jobs": metrics.retry_jobs,
                "flush_deferred_jobs": metrics.deferred_jobs,
                "invalid_json_files": integrity["mid_term_invalid_json_files"],
                "tmp_files": integrity["mid_term_tmp_files"],
            }
        )
    return results


async def main() -> None:
    logging.getLogger().setLevel(logging.CRITICAL)
    started = datetime.now(UTC)
    data_dir = Path("data/stress_bench_core_" + started.strftime("%Y%m%d_%H%M%S"))
    data_dir.mkdir(parents=True, exist_ok=True)
    print("Stress run started:", started.isoformat().replace("+00:00", "Z"))
    print("Core data dir:", data_dir)

    # Core throughput/lock tests: disable maintenance to isolate chat core path.
    service, memory_manager, _, _ = build_chat_stack(
        data_dir,
        enable_flush=False,
        enable_compaction=False,
    )
    levels = [1, 2, 4, 8, 12, 16, 24]
    multi: list[LoadResult] = []
    same: list[LoadResult] = []
    for conc in levels:
        total = max(120, conc * 12)
        multi.append(
            await run_chat_load(
                service=service,
                scenario_name="multi_session",
                concurrency=conc,
                total_requests=total,
                same_session=False,
                skill_names=["base", "memory"],
            )
        )
        same.append(
            await run_chat_load(
                service=service,
                scenario_name="same_session",
                concurrency=conc,
                total_requests=total,
                same_session=True,
                skill_names=["base", "memory"],
            )
        )

    print_result_table("Core multi-session parallel", multi)
    print_result_table("Core same-session lock contention", same)
    print()
    print_threshold("core_multi_session", summarize_threshold(multi))
    print_threshold("core_same_session", summarize_threshold(same))

    memory_consistency = await run_memory_write_consistency_stress(
        memory_manager=memory_manager,
        data_dir=data_dir,
        total_writes=800,
        concurrency=24,
    )
    print()
    print("=== Memory write consistency ===")
    print(json.dumps(memory_consistency, ensure_ascii=False, indent=2))

    maintenance_sweep = await run_maintenance_race_sweep()
    print()
    print("=== Flush+compaction race sweep (same session) ===")
    print(json.dumps(maintenance_sweep, ensure_ascii=False, indent=2))

    ended = datetime.now(UTC)
    print()
    print("Stress run finished:", ended.isoformat().replace("+00:00", "Z"))
    print("Elapsed seconds:", round((ended - started).total_seconds(), 2))


if __name__ == "__main__":
    asyncio.run(main())
