"""Process-level smoke for write failure interrupt and restart recovery."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.settings import Settings
from tools.smoke_career_live_flow import build_live_stack, tool_call_counts
from tools.smoke_langgraph_restart_resume import (
    ProcessHandle,
    _first_application_id,
    _post_sse,
    _record_counts_for_session,
    _require_event,
    _required_int,
    _required_string,
    _seed_session,
    _stop_server,
    _wait_for_server,
)


@dataclass(slots=True)
class WriteRetryReport:
    success: bool
    session_id: str
    workflow_instance_id: str | None
    failed_node: str | None
    retry_workflow_version: int | None
    tool_call_counts: dict[str, int]
    record_counts: dict[str, int]
    process_logs: list[str]
    errors: list[str]


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[1]
    data_dir = args.data_dir.resolve()
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    session_id = f"sess_m61_write_retry_{uuid4().hex[:10]}"
    report = WriteRetryReport(False, session_id, None, None, None, {}, {}, [], [])
    settings = Settings.load().model_copy(
        update={"data_dir": data_dir, "langgraph_workflow_enabled": False}
    )
    stack = build_live_stack(data_dir=data_dir, settings=settings)
    _seed_session(stack=stack, session_id=session_id)
    failure_state_path = data_dir / "langgraph" / "smoke_write_failures.json"

    try:
        port = _free_port()
        base_url = f"http://127.0.0.1:{port}"
        first = _start_server(
            root=root,
            data_dir=data_dir,
            failure_state_path=failure_state_path,
            port=port,
            index=1,
        )
        report.process_logs.append(str(first.log_path))
        try:
            start_events = _post_sse(
                base_url,
                "/api/chat/stream",
                {
                    "session_id": session_id,
                    "message": (
                        "我刚面完星河智能 AI 应用开发岗位的一面。请保存面试复盘 Note，"
                        "并更新当前求职项目的阶段、风险、下一步行动和项目备注。"
                    ),
                    "skill_names": ["base", "tools", "memory", "file-reader"],
                    "max_tool_rounds": 24,
                    "trace_level": "verbose",
                },
                args.request_timeout_seconds,
            )
            scope = _require_event(start_events, "workflow_waiting_for_input", payload_type="interview_review_scope")
            workflow_instance_id = _required_string(scope, "workflow_instance_id")
            report.workflow_instance_id = workflow_instance_id
            confirmation_events = _post_sse(
                base_url,
                f"/api/workflows/{workflow_instance_id}/resume/stream",
                {
                    "session_id": session_id,
                    "expected_version": _required_int(scope, "workflow_version"),
                    "payload": {
                        "selected_application_id": _first_application_id(scope),
                        "save_note": True,
                        "update_application": True,
                        "update_fields": ["stage", "risks", "next_actions", "notes"],
                    },
                    "trace_level": "verbose",
                },
                args.request_timeout_seconds,
            )
            confirmation = _require_event(
                confirmation_events,
                "workflow_waiting_for_input",
                payload_type="interview_review_confirmation",
            )
            failed_events = _post_sse(
                base_url,
                f"/api/workflows/{workflow_instance_id}/resume/stream",
                {
                    "session_id": session_id,
                    "expected_version": _required_int(confirmation, "workflow_version"),
                    "payload": {"action": "approve"},
                    "trace_level": "verbose",
                },
                args.request_timeout_seconds,
            )
            retry = _require_event(
                failed_events,
                "workflow_waiting_for_input",
                payload_type="workflow_write_retry",
            )
            report.failed_node = _required_string(retry, "failed_node")
            report.retry_workflow_version = _required_int(retry, "workflow_version")
        finally:
            _stop_server(first)

        second = _start_server(
            root=root,
            data_dir=data_dir,
            failure_state_path=failure_state_path,
            port=port,
            index=2,
        )
        report.process_logs.append(str(second.log_path))
        try:
            final_events = _post_sse(
                base_url,
                f"/api/workflows/{report.workflow_instance_id}/resume/stream",
                {
                    "session_id": session_id,
                    "expected_version": report.retry_workflow_version,
                    "payload": {"action": "retry"},
                    "trace_level": "verbose",
                },
                args.request_timeout_seconds,
            )
            _require_event(final_events, "workflow_completed")
            _require_event(final_events, "done")
        finally:
            _stop_server(second)

        report.tool_call_counts = tool_call_counts(stack.session_repository, session_id)
        report.record_counts = _record_counts_for_session(stack=stack, session_id=session_id)
        if report.failed_node != "merge_career_application":
            report.errors.append(f"unexpected failed node: {report.failed_node}")
        if report.tool_call_counts.get("note_create") != 1:
            report.errors.append(f"note_create count: {report.tool_call_counts.get('note_create')}")
        if report.tool_call_counts.get("career_application_merge") != 3:
            report.errors.append(
                f"career_application_merge count: {report.tool_call_counts.get('career_application_merge')}"
            )
        if report.record_counts.get("career_applications") != 1:
            report.errors.append(f"career application count: {report.record_counts.get('career_applications')}")
        if report.errors:
            raise RuntimeError("; ".join(report.errors))
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


def _start_server(
    *,
    root: Path,
    data_dir: Path,
    failure_state_path: Path,
    port: int,
    index: int,
) -> ProcessHandle:
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
            "LANGGRAPH_NODE_RETRY_ATTEMPTS": "2",
            "LANGGRAPH_SMOKE_FAIL_WRITE_TOOL": "career_application_merge",
            "LANGGRAPH_SMOKE_FAIL_WRITE_ATTEMPTS": "2",
            "LANGGRAPH_SMOKE_FAILURE_STATE_PATH": str(failure_state_path),
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
            "tools.smoke_langgraph_write_retry_app:app",
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


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run LangGraph write retry restart smoke.")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/live_smoke_m61_write_retry"),
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=Path("data/live_smoke_m61_write_retry/report.json"),
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)
    return parser.parse_args()


if __name__ == "__main__":
    main()
