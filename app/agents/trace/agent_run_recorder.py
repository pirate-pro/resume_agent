from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.agents.runtime import AgentResult, serialize_payload
from app.infra.storage.workspace import WorkspaceManager


class AgentRunRecorder:
    def __init__(
        self,
        *,
        task_id: str,
        stage: str,
        mode: str,
        objective: str,
        attempt: int,
        workspace: WorkspaceManager | None = None,
    ) -> None:
        self._task_id = task_id
        self._stage = stage
        self._mode = mode
        self._objective = objective
        self._attempt = attempt
        self._workspace = workspace or WorkspaceManager()
        self._started_at = datetime.now(UTC)
        self._events: list[dict] = []
        self._run_id = f"{stage}-{self._started_at.strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:8]}"

        workspace_paths = self._workspace.create_task_workspace(task_id)
        self._run_dir = Path(workspace_paths["root"]) / "agent_runs" / self._run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self._run_dir / "manifest.json"
        self._contexts_path = self._run_dir / "contexts.json"
        self._timeline_path = self._run_dir / "timeline.jsonl"
        self._summary_path = self._run_dir / "summary.md"

        self._manifest: dict[str, Any] = {
            "task_id": task_id,
            "run_id": self._run_id,
            "stage": stage,
            "mode": mode,
            "attempt": attempt,
            "objective": objective,
            "started_at": self._started_at.isoformat(),
            "status": "running",
        }
        self._write_json(self._manifest_path, self._manifest)
        self.log_event(
            "run.started",
            {
                "task_id": task_id,
                "stage": stage,
                "mode": mode,
                "attempt": attempt,
                "objective": objective,
            },
        )

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def run_dir(self) -> str:
        return str(self._run_dir)

    def record_contexts(self, contexts: dict) -> None:
        self._write_json(self._contexts_path, contexts)

    def log_event(
        self,
        event_type: str,
        payload: Any,
        *,
        level: str = "info",
        agent_name: str | None = None,
        context_id: str | None = None,
    ) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event_type": event_type,
            "level": level,
            "agent_name": agent_name,
            "context_id": context_id,
            "payload": serialize_payload(payload),
        }
        self._events.append(event)
        with self._timeline_path.open("a", encoding="utf-8") as timeline:
            timeline.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def finalize(
        self,
        *,
        result: AgentResult,
        plan_steps: list[str],
        contexts: dict,
        delegated_agent: dict | None = None,
    ) -> dict:
        ended_at = datetime.now(UTC)
        duration_sec = round((ended_at - self._started_at).total_seconds(), 3)
        self._manifest.update(
            {
                "ended_at": ended_at.isoformat(),
                "duration_sec": duration_sec,
                "status": result.status,
                "failure_reason": result.failure_reason,
                "next_stage_hint": result.next_stage_hint,
                "confidence": result.confidence,
                "event_count": len(self._events),
                "plan_step_count": len(plan_steps),
                "delegated_agent": delegated_agent,
            }
        )
        self._write_json(self._manifest_path, self._manifest)
        self._write_json(self._contexts_path, contexts)
        self._summary_path.write_text(
            self._build_summary(
                result=result,
                plan_steps=plan_steps,
                contexts=contexts,
                delegated_agent=delegated_agent,
                duration_sec=duration_sec,
            ),
            encoding="utf-8",
        )
        return self._trace_info()

    def _build_summary(
        self,
        *,
        result: AgentResult,
        plan_steps: list[str],
        contexts: dict,
        delegated_agent: dict | None,
        duration_sec: float,
    ) -> str:
        lines = [
            "# Agent Run Summary",
            "",
            f"- task_id: {self._task_id}",
            f"- run_id: {self._run_id}",
            f"- stage: {self._stage}",
            f"- mode: {self._mode}",
            f"- status: {result.status}",
            f"- started_at: {self._started_at.isoformat()}",
            f"- duration_sec: {duration_sec}",
            f"- confidence: {result.confidence}",
            f"- failure_reason: {result.failure_reason or ''}",
            "",
            "## Objective",
            self._objective,
            "",
            "## Plan",
        ]
        if plan_steps:
            for index, step in enumerate(plan_steps, start=1):
                lines.append(f"{index}. {step}")
        else:
            lines.append("No explicit plan steps captured.")

        lines.extend(["", "## Delegation"])
        if delegated_agent is None:
            lines.append("No delegated agent metadata.")
        else:
            lines.append(f"- delegated_agent: {delegated_agent.get('name', '')}")
            lines.append(f"- delegated_mode: {delegated_agent.get('mode', '')}")

        lines.extend(["", "## Context Frames"])
        for frame in contexts.values():
            lines.append(
                f"- {frame.get('agent_name')} ({frame.get('mode')}) "
                f"context_id={frame.get('context_id')} parent={frame.get('parent_context_id')}"
            )

        lines.extend(["", "## Timeline Highlights"])
        for event in self._events[:30]:
            snippet = self._payload_snippet(event.get("payload"))
            lines.append(f"- {event['timestamp']} | {event['event_type']} | {snippet}")
        if len(self._events) > 30:
            lines.append(f"- ... {len(self._events) - 30} more events in timeline.jsonl")

        lines.extend(
            [
                "",
                "## Result",
                f"- next_stage_hint: {result.next_stage_hint or ''}",
                f"- observations_count: {len(result.observations)}",
                f"- tool_trace_count: {len(result.tool_traces)}",
            ]
        )
        return "\n".join(lines) + "\n"

    def _payload_snippet(self, payload: Any) -> str:
        serialized = serialize_payload(payload)
        if isinstance(serialized, dict):
            keys = ", ".join(list(serialized.keys())[:4])
            return f"dict[{keys}]"
        if isinstance(serialized, list):
            return f"list(len={len(serialized)})"
        text = str(serialized)
        return text[:120]

    def _trace_info(self) -> dict:
        return {
            "run_id": self._run_id,
            "run_dir": str(self._run_dir),
            "manifest_path": str(self._manifest_path),
            "contexts_path": str(self._contexts_path),
            "timeline_path": str(self._timeline_path),
            "summary_path": str(self._summary_path),
        }

    def _write_json(self, path: Path, payload: Any) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
