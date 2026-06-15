"""Process-level smoke for durable LangGraph restart and concurrent resume.

Run:
  uv run python tools/smoke_langgraph_restart_resume.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

import httpx

from app.core.settings import Settings
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from tools.smoke_career_live_flow import add_jd_artifact, add_resume_artifact, build_live_stack, tool_call_counts
from tools.smoke_live_matrix import _record_counts_for_session, _seed_retrieval_products


@dataclass(slots=True)
class ProcessHandle:
    process: subprocess.Popen[str]
    log_handle: TextIO
    log_path: Path


@dataclass(slots=True)
class RestartResumeReport:
    success: bool
    session_id: str
    workflow_instance_id: str | None
    initial_workflow_version: int | None
    resumed_workflow_version: int | None
    concurrent_success_count: int
    concurrent_rejection_count: int
    concurrent_rejection_details: list[str]
    tool_call_counts: dict[str, int]
    record_counts: dict[str, int]
    workflow_event_counts: dict[str, int]
    process_logs: list[str]
    errors: list[str]


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    data_dir = args.data_dir.resolve()
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    session_id = f"sess_m61_restart_{uuid4().hex[:10]}"
    report = RestartResumeReport(
        success=False,
        session_id=session_id,
        workflow_instance_id=None,
        initial_workflow_version=None,
        resumed_workflow_version=None,
        concurrent_success_count=0,
        concurrent_rejection_count=0,
        concurrent_rejection_details=[],
        tool_call_counts={},
        record_counts={},
        workflow_event_counts={},
        process_logs=[],
        errors=[],
    )
    settings = Settings.load().model_copy(
        update={
            "data_dir": data_dir,
            "langgraph_workflow_enabled": False,
        }
    )
    stack = build_live_stack(data_dir=data_dir, settings=settings)
    _seed_session(stack=stack, session_id=session_id)

    try:
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"

        first = _start_server(root=root, data_dir=data_dir, port=port, index=1)
        report.process_logs.append(str(first.log_path))
        try:
            start_events = _post_sse(
                base_url,
                "/api/chat/stream",
                {
                    "session_id": session_id,
                    "message": (
                        "我刚面完星河智能 AI 应用开发岗位的一面。请把这次面试复盘保存成一条 Note，"
                        "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
                        "面试里问到了 RAG chunk 策略、向量召回评估、Celery 延迟队列和 Agent 工具权限边界。"
                    ),
                    "skill_names": ["base", "tools", "memory", "file-reader"],
                    "max_tool_rounds": 24,
                    "trace_level": "verbose",
                },
                timeout_seconds=args.request_timeout_seconds,
            )
            scope = _require_event(start_events, "workflow_waiting_for_input", payload_type="interview_review_scope")
            workflow_instance_id = _required_string(scope, "workflow_instance_id")
            initial_version = _required_int(scope, "workflow_version")
            application_id = _first_application_id(scope)
            report.workflow_instance_id = workflow_instance_id
            report.initial_workflow_version = initial_version
        finally:
            _stop_server(first)

        second_port = _free_port()
        second = _start_server(root=root, data_dir=data_dir, port=port, index=2)
        parallel = _start_server(root=root, data_dir=data_dir, port=second_port, index=3)
        report.process_logs.extend([str(second.log_path), str(parallel.log_path)])
        try:
            scope_resume = {
                "session_id": session_id,
                "expected_version": initial_version,
                "payload": {
                    "selected_application_id": application_id,
                    "save_note": True,
                    "update_application": True,
                    "update_fields": ["stage", "risks", "next_actions", "notes"],
                    "user_supplement": (
                        "补充：重点记录语义 chunk、hit rate/precision、人工抽检闭环和 Agent 工具权限边界。"
                    ),
                },
                "trace_level": "verbose",
            }
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(
                        _post_sse,
                        target_base_url,
                        f"/api/workflows/{workflow_instance_id}/resume/stream",
                        scope_resume,
                        args.request_timeout_seconds,
                    )
                    for target_base_url in (base_url, f"http://127.0.0.1:{second_port}")
                ]
                concurrent_results = [future.result() for future in futures]

            confirmation_payloads: list[dict[str, Any]] = []
            rejection_details: list[str] = []
            for events in concurrent_results:
                confirmation = _find_event(
                    events,
                    "workflow_waiting_for_input",
                    payload_type="interview_review_confirmation",
                )
                if confirmation is not None:
                    confirmation_payloads.append(confirmation)
                    continue
                error = _find_event(events, "error")
                rejection_details.append(str((error or {}).get("detail") or "missing expected confirmation/error event"))
            report.concurrent_success_count = len(confirmation_payloads)
            report.concurrent_rejection_count = len(rejection_details)
            report.concurrent_rejection_details = rejection_details
            if len(confirmation_payloads) != 1 or len(rejection_details) != 1:
                raise RuntimeError(
                    "concurrent resume gate failed: "
                    f"success={len(confirmation_payloads)} rejection={len(rejection_details)}"
                )
            resumed_version = _required_int(confirmation_payloads[0], "workflow_version")
            if resumed_version <= initial_version:
                raise RuntimeError(
                    f"workflow version did not advance: initial={initial_version} resumed={resumed_version}"
                )
            report.resumed_workflow_version = resumed_version
        finally:
            _stop_server(second)
            _stop_server(parallel)

        third = _start_server(root=root, data_dir=data_dir, port=port, index=4)
        report.process_logs.append(str(third.log_path))
        try:
            final_events = _post_sse(
                base_url,
                f"/api/workflows/{workflow_instance_id}/resume/stream",
                {
                    "session_id": session_id,
                    "expected_version": resumed_version,
                    "payload": {"action": "approve"},
                    "trace_level": "verbose",
                },
                timeout_seconds=args.request_timeout_seconds,
            )
            _require_event(final_events, "workflow_completed")
            done = _require_event(final_events, "done")
            answer = _required_string(done, "answer")
            if "note_id:" not in answer or "application_id:" not in answer:
                raise RuntimeError(f"unexpected final answer: {answer}")
        finally:
            _stop_server(third)

        report.tool_call_counts = tool_call_counts(stack.session_repository, session_id)
        report.record_counts = _record_counts_for_session(stack=stack, session_id=session_id)
        report.workflow_event_counts = _workflow_event_counts(stack.session_repository, session_id)
        _verify_outputs(report)
        report.success = True
    except Exception as exc:  # noqa: BLE001
        report.errors.append(str(exc) or exc.__class__.__name__)

    output_path = args.json_report.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    print(f"JSON report: {output_path}")
    if not report.success:
        raise SystemExit(1)


def _seed_session(*, stack: Any, session_id: str) -> None:
    stack.session_repository.create_session(session_id)
    stack.session_repository.update_session_title(session_id, "M61 restart resume smoke")
    resume_artifact_id = "artifact_resume_m61_restart"
    jd_artifact_id = "artifact_jd_m61_restart"
    add_resume_artifact(stack.session_repository, session_id=session_id, artifact_id=resume_artifact_id)
    add_jd_artifact(stack.session_repository, session_id=session_id, artifact_id=jd_artifact_id)
    _seed_retrieval_products(
        stack=stack,
        session_id=session_id,
        resume_artifact_id=resume_artifact_id,
        jd_artifact_id=jd_artifact_id,
    )
    stack.session_repository.set_active_artifact_ids(session_id, [resume_artifact_id, jd_artifact_id])


def _start_server(*, root: Path, data_dir: Path, port: int, index: int) -> ProcessHandle:
    env = dict(os.environ)
    env.update(
        {
            "DATA_DIR": str(data_dir),
            "PYTHONPATH": f"{root}{os.pathsep}{env.get('PYTHONPATH', '')}",
            "LANGGRAPH_WORKFLOW_ENABLED": "true",
            "LANGGRAPH_INTERACTIVE_NOTE_ENABLED": "false",
            "LANGGRAPH_INTERACTIVE_INTERVIEW_REVIEW_ENABLED": "true",
            "LANGGRAPH_WORKFLOW_BACKEND": "sqlite",
            "LANGGRAPH_CHECKPOINT_PATH": str(data_dir / "langgraph" / "checkpoints.sqlite"),
            "LANGGRAPH_RESUME_LEASE_PATH": str(data_dir / "langgraph" / "resume_locks.sqlite"),
            "MID_TERM_FLUSH_WORKER_ENABLED": "false",
            "RETRIEVAL_TOOL_BACKEND": "mcp",
        }
    )
    log_path = data_dir / "process_logs" / f"uvicorn_{index}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            "1",
        ],
        cwd=root,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
    )
    handle = ProcessHandle(process=process, log_handle=log_handle, log_path=log_path)
    _wait_for_server(handle, port=port)
    return handle


def _wait_for_server(handle: ProcessHandle, *, port: int) -> None:
    deadline = time.monotonic() + 20
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if handle.process.poll() is not None:
            handle.log_handle.flush()
            raise RuntimeError(f"Uvicorn exited early; see {handle.log_path}")
        try:
            response = httpx.get(f"http://127.0.0.1:{port}/health", timeout=1.0)
            if response.status_code == 200:
                return
        except (httpx.HTTPError, OSError) as exc:
            last_error = exc
        time.sleep(0.1)
    raise RuntimeError(f"Uvicorn did not become ready on port {port}: {last_error}; see {handle.log_path}")


def _stop_server(handle: ProcessHandle) -> None:
    try:
        if handle.process.poll() is None:
            handle.process.terminate()
            try:
                handle.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                handle.process.kill()
                handle.process.wait(timeout=5)
    finally:
        handle.log_handle.close()


def _post_sse(
    base_url: str,
    path: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> list[tuple[str, dict[str, Any]]]:
    response = httpx.post(
        f"{base_url}{path}",
        json=payload,
        timeout=httpx.Timeout(timeout_seconds),
    )
    response.raise_for_status()
    return _parse_sse(response.text)


def _parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_name = line[6:].strip() or "message"
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        payload = json.loads("\n".join(data_lines)) if data_lines else {}
        if isinstance(payload, dict):
            events.append((event_name, payload))
    return events


def _find_event(
    events: list[tuple[str, dict[str, Any]]],
    event_name: str,
    *,
    payload_type: str | None = None,
) -> dict[str, Any] | None:
    for name, payload in events:
        if name != event_name:
            continue
        if payload_type is not None and payload.get("type") != payload_type:
            continue
        return payload
    return None


def _require_event(
    events: list[tuple[str, dict[str, Any]]],
    event_name: str,
    *,
    payload_type: str | None = None,
) -> dict[str, Any]:
    payload = _find_event(events, event_name, payload_type=payload_type)
    if payload is not None:
        return payload
    error = _find_event(events, "error")
    if error is not None:
        raise RuntimeError(str(error.get("detail") or error))
    raise RuntimeError(f"missing SSE event: event={event_name} type={payload_type}")


def _first_application_id(payload: dict[str, Any]) -> str:
    candidates = payload.get("application_candidates")
    if isinstance(candidates, list):
        for item in candidates:
            if isinstance(item, dict):
                value = item.get("application_id")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    raise RuntimeError("interview review scope did not include application candidate")


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise RuntimeError(f"payload missing string field: {key}")


def _required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int) and value > 0:
        return value
    raise RuntimeError(f"payload missing positive integer field: {key}")


def _workflow_event_counts(repository: JsonlSessionRepository, session_id: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in repository.list_events(session_id):
        if event.type.startswith("workflow_"):
            counts[event.type] = counts.get(event.type, 0) + 1
    return counts


def _verify_outputs(report: RestartResumeReport) -> None:
    expected_tools = {
        "retrieval_search": 1,
        "retrieval_context_pack": 1,
        "note_create": 1,
        "career_application_merge": 1,
    }
    for tool_name, expected in expected_tools.items():
        actual = report.tool_call_counts.get(tool_name, 0)
        if actual != expected:
            report.errors.append(f"{tool_name}: expected={expected} actual={actual}")
    if report.record_counts.get("notes") != 2:
        report.errors.append(f"notes: expected=2 actual={report.record_counts.get('notes', 0)}")
    if report.record_counts.get("career_applications") != 1:
        report.errors.append(
            f"career_applications: expected=1 actual={report.record_counts.get('career_applications', 0)}"
        )
    if report.workflow_event_counts.get("workflow_waiting_for_input") != 2:
        report.errors.append(
            "workflow_waiting_for_input: "
            f"expected=2 actual={report.workflow_event_counts.get('workflow_waiting_for_input', 0)}"
        )
    if report.workflow_event_counts.get("workflow_completed") != 1:
        report.errors.append(
            f"workflow_completed: expected=1 actual={report.workflow_event_counts.get('workflow_completed', 0)}"
        )
    if report.concurrent_success_count != 1 or report.concurrent_rejection_count != 1:
        report.errors.append(
            "concurrent resume: "
            f"success={report.concurrent_success_count} rejection={report.concurrent_rejection_count}"
        )
    if not any("already being resumed" in detail for detail in report.concurrent_rejection_details):
        report.errors.append(
            "cross-process resume lease was not observed: "
            f"details={report.concurrent_rejection_details}"
        )
    if report.errors:
        raise RuntimeError("; ".join(report.errors))


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run process-level LangGraph restart/resume smoke.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/live_smoke_m61_restart_resume"),
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=Path("data/live_smoke_m61_restart_resume/report.json"),
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)
    args = parser.parse_args()
    if args.request_timeout_seconds <= 0:
        parser.error("--request-timeout-seconds must be positive")
    return args


if __name__ == "__main__":
    main()
