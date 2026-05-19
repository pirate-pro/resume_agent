"""Report prompt context token breakdown from llm_usage events.

Run:
  uv run python tools/report_context_token_breakdown.py --data-dir data/live_x/run_001 --session-id sess_x
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def main() -> None:
    args = _parse_args()
    events_path = args.data_dir / "sessions" / args.session_id / "events.jsonl"
    if not events_path.exists():
        raise SystemExit(f"events.jsonl not found: {events_path}")
    calls = _read_usage_calls(events_path)
    if not calls:
        raise SystemExit("No llm_usage events found.")
    _print_summary(calls)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report llm prompt context token breakdown.")
    parser.add_argument("--data-dir", type=Path, required=True, help="Run data directory, e.g. data/live/run_001.")
    parser.add_argument("--session-id", required=True)
    return parser.parse_args()


def _read_usage_calls(path: Path) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("type") != "llm_usage":
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        calls.append(
            {
                "agent_id": event.get("agent_id") or "unknown",
                "run_id": event.get("run_id") or "unknown",
                "round_index": payload.get("round_index"),
                "prompt_tokens": _int(payload.get("prompt_tokens")),
                "total_tokens": _int(payload.get("total_tokens")),
                "tool_schema_count": _int(payload.get("tool_schema_count")),
                "prompt_estimate_total_tokens": _int(payload.get("prompt_estimate_total_tokens")),
                "system_prompt_estimate_tokens": _int(payload.get("system_prompt_estimate_tokens")),
                "messages_estimate_tokens": _int(payload.get("messages_estimate_tokens")),
                "tools_estimate_tokens": _int(payload.get("tools_estimate_tokens")),
                "message_user_estimate_tokens": _int(payload.get("message_user_estimate_tokens")),
                "message_assistant_estimate_tokens": _int(payload.get("message_assistant_estimate_tokens")),
                "message_tool_estimate_tokens": _int(payload.get("message_tool_estimate_tokens")),
                "message_other_estimate_tokens": _int(payload.get("message_other_estimate_tokens")),
                "tool_context_window_mode": str(payload.get("tool_context_window_mode") or "off"),
                "pending_tool_message_count": _int(payload.get("pending_tool_message_count")),
                "compacted_tool_observation_count": _int(payload.get("compacted_tool_observation_count")),
                "tool_state_message_estimate_tokens": _int(payload.get("tool_state_message_estimate_tokens")),
                "tool_pending_message_estimate_tokens": _int(payload.get("tool_pending_message_estimate_tokens")),
                "workflow_rule_selection_mode": str(payload.get("workflow_rule_selection_mode") or "none"),
                "workflow_rule_pack_names": _read_string_list(payload.get("workflow_rule_pack_names")),
                "workflow_rules_estimate_tokens": _int(payload.get("workflow_rules_estimate_tokens")),
                "system_prompt_sections": _read_sections(payload.get("system_prompt_sections")),
            }
        )
    return calls


def _print_summary(calls: list[dict[str, Any]]) -> None:
    print("=== 上下文 Token 拆分 ===")
    print(f"调用数: {len(calls)}")
    print(f"provider_prompt_tokens: {sum(item['prompt_tokens'] for item in calls)}")
    estimate_total = sum(item["prompt_estimate_total_tokens"] for item in calls)
    print(f"estimated_prompt_tokens: {estimate_total}")
    fields = [
        ("system_prompt", "system_prompt_estimate_tokens"),
        ("messages", "messages_estimate_tokens"),
        ("tools", "tools_estimate_tokens"),
        ("message_user", "message_user_estimate_tokens"),
        ("message_assistant", "message_assistant_estimate_tokens"),
        ("message_tool", "message_tool_estimate_tokens"),
        ("message_other", "message_other_estimate_tokens"),
        ("tool_state_message", "tool_state_message_estimate_tokens"),
        ("tool_pending_message", "tool_pending_message_estimate_tokens"),
        ("workflow_rules", "workflow_rules_estimate_tokens"),
    ]
    for label, field in fields:
        value = sum(item[field] for item in calls)
        ratio = value / estimate_total if estimate_total else 0
        print(f"{label}: {value} ({ratio:.1%})")

    section_totals = _section_totals(calls)
    if section_totals:
        print("\n=== system prompt section 汇总 ===")
        for name, tokens in section_totals[:15]:
            ratio = tokens / estimate_total if estimate_total else 0
            print(f"{name}: {tokens} ({ratio:.1%})")

    print("\n=== 按 run 汇总 ===")
    for key, items in _group_by_run(calls).items():
        prompt = sum(item["prompt_tokens"] for item in items)
        estimate = sum(item["prompt_estimate_total_tokens"] for item in items)
        system = sum(item["system_prompt_estimate_tokens"] for item in items)
        messages = sum(item["messages_estimate_tokens"] for item in items)
        tools = sum(item["tools_estimate_tokens"] for item in items)
        schemas = sorted({item["tool_schema_count"] for item in items})
        window_modes = sorted({str(item["tool_context_window_mode"]) for item in items})
        workflow_modes = sorted({str(item["workflow_rule_selection_mode"]) for item in items})
        workflow_packs = sorted({pack for item in items for pack in item["workflow_rule_pack_names"]})
        compacted = sum(item["compacted_tool_observation_count"] for item in items)
        pending_tool_messages = sum(item["pending_tool_message_count"] for item in items)
        print(
            f"{key}: calls={len(items)} provider_prompt={prompt} estimate={estimate} "
            f"system={system} messages={messages} tools={tools} schemas={schemas} "
            f"tool_window={window_modes} workflow_rules={workflow_modes} "
            f"workflow_packs={workflow_packs[:8]} compacted_observations={compacted} "
            f"pending_tool_messages={pending_tool_messages}"
        )
        run_sections = _section_totals(items)[:5]
        if run_sections:
            print("  top_sections: " + ", ".join(f"{name}={tokens}" for name, tokens in run_sections))


def _group_by_run(calls: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in calls:
        key = f"{item['agent_id']}:{item['run_id']}"
        grouped.setdefault(key, []).append(item)
    return grouped


def _section_totals(calls: list[dict[str, Any]]) -> list[tuple[str, int]]:
    totals: dict[str, int] = {}
    for call in calls:
        sections = call.get("system_prompt_sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            name = str(section.get("name") or "").strip()
            if not name:
                continue
            totals[name] = totals.get(name, 0) + _int(section.get("tokens"))
    return sorted(totals.items(), key=lambda item: (item[1], item[0]), reverse=True)


def _read_sections(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    sections: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        sections.append(
            {
                "name": name,
                "tokens": _int(item.get("tokens")),
                "chars": _int(item.get("chars")),
                "item_count": _int(item.get("item_count")),
                "pack_names": _read_string_list(item.get("pack_names")),
                "selection_mode": str(item.get("selection_mode") or ""),
            }
        )
    return sections


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _read_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for item in value:
        normalized = str(item).strip()
        if normalized:
            output.append(normalized)
    return output


if __name__ == "__main__":
    main()
