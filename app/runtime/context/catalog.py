"""Skill/tool catalog rendering helpers."""

from __future__ import annotations

from app.domain.models import ToolDefinition


_COMPACT_GROUPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "artifact",
        ("session_", "workspace_", "publish_artifact"),
        "会话资料读取、搜索、创建和上传文件处理。",
    ),
    (
        "retrieval",
        ("retrieval_",),
        "从已保存的产品记录、笔记、学习任务和资料库中召回上下文。",
    ),
    (
        "career",
        ("career_",),
        "求职产品资产：简历画像、职业画像、JD 分析、匹配报告、简历版本和求职项目。",
    ),
    (
        "note",
        ("note_",),
        "用户笔记的创建、读取、追加、编辑和归档。",
    ),
    (
        "learning",
        ("learning_",),
        "学习计划、学习任务、打卡和短板跟踪。",
    ),
    (
        "memory",
        ("memory_",),
        "长期偏好、稳定事实和长期记忆的读写。",
    ),
    (
        "delegation",
        ("delegate_agents", "agent_task_status"),
        "委派 child-agent 并查询委派任务状态。",
    ),
    (
        "state",
        ("state_",),
        "运行状态和工作视图更新；普通业务任务通常不需要。",
    ),
)
_COMPACT_CORE_TOOL_NAMES = {"tool_search"}


def fallback_skill_description(*, name: str, instructions: str) -> str:
    for raw_line in instructions.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        if line.startswith("-"):
            line = line.lstrip("-").strip()
        if line:
            return line[:240]
    return f"Loaded skill: {name}"


def catalog_description(description: str, *, max_chars: int = 140) -> str:
    normalized = " ".join(description.strip().split())
    if not normalized:
        return "No description."
    first_sentence = normalized.split(". ", 1)[0].rstrip(".")
    if len(first_sentence) <= max_chars:
        return first_sentence + "."
    return first_sentence[: max_chars - 1].rstrip() + "."


def render_full_tool_catalog(tool_definitions: list[ToolDefinition]) -> str:
    return "Tools:\n" + "\n".join(
        f"- {definition.name}: {catalog_description(definition.description)}"
        for definition in tool_definitions
    )


def render_compact_search_tool_catalog(
    tool_definitions: list[ToolDefinition],
    *,
    visible_tool_names: list[str],
) -> str:
    """Render a compact capability directory for progressive schema disclosure."""

    definitions_by_name = {definition.name: definition for definition in tool_definitions}
    visible_definitions = [
        definitions_by_name[name]
        for name in _dedupe(visible_tool_names)
        if name in definitions_by_name
    ]
    if not visible_definitions and "tool_search" in definitions_by_name:
        visible_definitions = [definitions_by_name["tool_search"]]

    lines = [
        "Tools:",
        "Search disclosure mode is active: only the currently visible tool schemas can be called.",
    ]
    if visible_definitions:
        lines.append("Visible tool schemas now:")
        lines.extend(
            f"- {definition.name}: {catalog_description(definition.description)}"
            for definition in visible_definitions
        )
    lines.extend(
        [
            "Available capability groups through tool_search:",
            *_format_available_group_lines(tool_definitions),
            "Use tool_search when a needed capability is not visible; after it reveals tool names, call those tools directly.",
        ]
    )
    return "\n".join(lines)


def _format_available_group_lines(tool_definitions: list[ToolDefinition]) -> list[str]:
    output: list[str] = []
    for group_name, prefixes, description in _COMPACT_GROUPS:
        count = sum(1 for definition in tool_definitions if _matches_any_prefix(definition.name, prefixes))
        if count <= 0:
            continue
        output.append(f"- {group_name} ({count}): {description}")
    other_count = sum(
        1
        for definition in tool_definitions
        if definition.name not in _COMPACT_CORE_TOOL_NAMES and not _known_group_name(definition.name)
    )
    if other_count:
        output.append(f"- other ({other_count}): 其他当前 agent 可用能力。")
    return output or ["- none (0): 当前没有可搜索的额外工具。"]


def _known_group_name(name: str) -> bool:
    return any(_matches_any_prefix(name, prefixes) for _, prefixes, _ in _COMPACT_GROUPS)


def _matches_any_prefix(name: str, prefixes: tuple[str, ...]) -> bool:
    for prefix in prefixes:
        if prefix.endswith("_") and name.startswith(prefix):
            return True
        if name == prefix:
            return True
    return False


def _dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        output.append(item)
        seen.add(item)
    return output
