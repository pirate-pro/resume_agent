"""Long-term summary derivation from stored memory facts."""

from __future__ import annotations

from app.memory.file_models import MemoryFact


def build_long_term_summaries_from_facts(facts: list[MemoryFact]) -> dict[str, str]:
    sorted_facts = sorted([fact for fact in facts if _is_standing_summary_fact(fact)], key=lambda item: item.updated_at, reverse=True)
    preference_facts = [
        item
        for item in sorted_facts
        if item.category in {"preference", "behavior", "correction"}
        or _has_any_tag(item.tags, {"preference", "response_style", "constraint", "rule", "policy"})
    ]
    work_context_facts = [
        item
        for item in sorted_facts
        if item.category in {"goal", "knowledge", "context"}
        or _has_any_tag(item.tags, {"goal", "knowledge", "stack", "project", "architecture", "tooling"})
    ]
    stable_background_facts = [
        item
        for item in sorted_facts
        if item.confidence >= 0.8
        or item.inject_policy == "always"
        or _has_any_tag(item.tags, {"long_term", "profile", "background"})
    ]
    recent_months_facts = sorted_facts[:8]
    earlier_context_facts = sorted(sorted_facts, key=lambda item: item.updated_at)[:6]
    top_of_mind_facts = sorted_facts[:6]
    return {
        "user.workContext": _compose_fact_bullets(work_context_facts, max_items=6),
        "user.personalContext": _compose_fact_bullets(preference_facts, max_items=6),
        "user.topOfMind": _compose_fact_bullets(top_of_mind_facts, max_items=6),
        "history.recentMonths": _compose_fact_bullets(recent_months_facts, max_items=8),
        "history.earlierContext": _compose_fact_bullets(earlier_context_facts, max_items=6),
        "history.longTermBackground": _compose_fact_bullets(stable_background_facts, max_items=6),
    }


def _is_standing_summary_fact(fact: MemoryFact) -> bool:
    return fact.inject_policy == "always"


def _compose_fact_bullets(facts: list[MemoryFact], *, max_items: int) -> str:
    if not facts or max_items <= 0:
        return ""
    lines: list[str] = []
    seen: set[str] = set()
    for fact in facts:
        content = _normalize_summary_line(fact.content)
        if not content:
            continue
        fingerprint = content.casefold()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        lines.append(f"- {content}")
        if len(lines) >= max_items:
            break
    return "\n".join(lines)


def _normalize_summary_line(content: str) -> str:
    normalized = " ".join(content.strip().split())
    if not normalized:
        return ""
    if len(normalized) <= 140:
        return normalized
    return normalized[:137].rstrip() + "..."


def _has_any_tag(tags: list[str], expected: set[str]) -> bool:
    normalized = {tag.strip().lower() for tag in tags if isinstance(tag, str) and tag.strip()}
    return bool(normalized.intersection(expected))
