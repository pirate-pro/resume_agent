"""Markdown rendering and writing for mid-term daily notes."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.time import normalize_app_datetime
from app.memory.file_store import FileMemoryStore
from app.runtime.mid_term.models import MidTermEventPack
from app.runtime.mid_term.shared import flush_id_for_pack, format_iso

_logger = logging.getLogger(__name__)


class MidTermDailyRenderer:
    """Render validated summary JSON into markdown blocks."""

    def render(self, *, summary: dict[str, Any], pack: MidTermEventPack, flushed_at: datetime) -> str:
        flush_id = flush_id_for_pack(pack)
        lines: list[str] = [
            f"## Flush {format_iso(flushed_at)}",
            f"<!-- flush_id: {flush_id} -->",
            "",
            "### Meta",
            f"- session_id: {pack.session_id}",
            f"- agent_id: {pack.agent_id}",
            f"- batch: {pack.batch_index}/{pack.batch_total}",
            f"- event_range: {pack.first_event_id}..{pack.last_event_id}",
            f"- event_count: {pack.event_count}",
            f"- delta_event_count: {pack.delta_event_count}",
            f"- semantic_units: {pack.selected_unit_count}",
            f"- signal_score: {pack.signal_score}",
            f"- input_estimated_tokens: {pack.input_estimated_tokens}",
            f"- input_budget_tokens: {pack.input_budget_tokens}",
            "",
            "### Active Context",
        ]
        lines.extend(_render_active_context(summary["active_context"]))
        lines.extend(["", "### Decisions"])
        lines.extend(_render_decisions(summary["decisions"]))
        lines.extend(["", "### Progress"])
        lines.extend(_render_progress(summary["progress"]))
        lines.extend(["", "### Open Questions"])
        lines.extend(_render_open_questions(summary["open_questions"]))
        lines.extend(["", "### Candidate Long-Term Memories"])
        lines.extend(_render_candidates(summary["candidate_long_term"]))
        lines.extend(["", "### Artifact References"])
        lines.extend(_render_artifact_refs(summary["artifact_refs"]))
        lines.extend(["", ""])
        return "\n".join(lines)


class MidTermDailyWriter:
    """Resolve and append daily note blocks."""

    def __init__(self, memory_store: FileMemoryStore) -> None:
        self._memory_store = memory_store

    def daily_path(self, *, agent_id: str, now: datetime) -> Path:
        base = self._memory_store.root_dir / "agents" / agent_id / "mid_term" / "daily"
        base.mkdir(parents=True, exist_ok=True)
        return base / f"{normalize_app_datetime(now).date().isoformat()}.md"

    def append_daily_block(self, path: Path, pack: MidTermEventPack, block: str) -> None:
        flush_id = flush_id_for_pack(pack)
        marker = f"<!-- flush_id: {flush_id} -->"
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if marker in existing:
                _logger.debug(
                    "mid-term daily append skipped (duplicate flush_id): session_id=%s agent_id=%s path=%s flush_id=%s",
                    pack.session_id,
                    pack.agent_id,
                    path,
                    flush_id,
                )
                return
            if not existing.strip():
                path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        else:
            path.write_text(f"# {path.stem}\n\n", encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(block)
        _logger.debug(
            "mid-term daily appended: session_id=%s agent_id=%s path=%s event_count=%s",
            pack.session_id,
            pack.agent_id,
            path,
            pack.event_count,
        )


def _render_active_context(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        output.append(
            f"- {item['summary']} [confidence={item['confidence']}] [evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_decisions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [
        f"- {item['summary']} [stability={item['stability']}] [evidence={','.join(item['evidence_event_ids'])}]"
        for item in items
    ]


def _render_progress(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        output.append(
            "- "
            + f"[CALL] {item['tool_name']} {item['call_summary']} | "
            + f"[RESULT] success={item['success']} {item['result_summary']} "
            + f"[evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_open_questions(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [f"- {item['question']} [evidence={','.join(item['evidence_event_ids'])}]" for item in items]


def _render_candidates(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    output: list[str] = []
    for item in items:
        tags = ",".join(item["tags"]) if item["tags"] else "-"
        output.append(
            f"- {item['content']} [tags={tags}] [confidence={item['confidence']}] "
            + f"[why={item['why_reusable']}] [evidence={','.join(item['evidence_event_ids'])}]"
        )
    return output


def _render_artifact_refs(items: list[dict[str, Any]]) -> list[str]:
    if not items:
        return ["- (none)"]
    return [
        f"- {item['path_or_artifact_id']} [reason={item['reason']}] [evidence={','.join(item['evidence_event_ids'])}]"
        for item in items
    ]
