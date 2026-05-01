"""Prompt section builder for context assembly."""

from __future__ import annotations

from app.domain.models import AgentIdentityDocuments, MemoryItem, SessionFile, ToolDefinition
from app.runtime.context.catalog import catalog_description
from app.runtime.context.constants import (
    MEMORY_ACCESS_RULES,
    MEMORY_LANE_LABELS,
    MEMORY_SCOPE_LABELS,
    OUTPUT_FORMAT_RULES,
)
from app.runtime.context.memory_sections import (
    format_memory_lines,
    group_memory_items_by_scope,
    section_key,
    split_memory_lanes,
)
from app.runtime.context.models import ContextAssemblyPlan, ContextAssemblyRole, ContextSection, ShortTermContextPlan
from app.runtime.context.short_term import (
    format_assigned_task_lines,
    format_child_result_summary_lines,
    format_context_summary_lines,
)


def build_assembly_plan(
    *,
    role: ContextAssemblyRole,
    skill_descriptions: dict[str, str],
    tool_definitions: list[ToolDefinition],
    agent_documents: AgentIdentityDocuments,
    short_term_plan: ShortTermContextPlan,
    memory_lanes: dict[str, list[MemoryItem]],
    active_files: list[SessionFile],
) -> ContextAssemblyPlan:
    memory_slices = split_memory_lanes(memory_lanes)
    sections: list[ContextSection] = [
        ContextSection(
            name="runtime_base",
            content="You are a pragmatic assistant. Use tools when needed and never fabricate tool results.",
        ),
        ContextSection(
            name="unknown_information_policy",
            content="If information is unknown, say you do not know.",
        ),
        ContextSection(name="output_format_rules", content=OUTPUT_FORMAT_RULES),
    ]
    if agent_documents.agent_markdown:
        sections.append(ContextSection(name="agent_identity", content="AGENT.md:\n" + agent_documents.agent_markdown))
    if agent_documents.soul_markdown:
        sections.append(ContextSection(name="soul_identity", content="SOUL.md:\n" + agent_documents.soul_markdown))
    if skill_descriptions:
        sections.append(
            ContextSection(
                name="skill_catalog",
                content="Skills:\n"
                + "\n".join(
                    f"- {name}: {description}" for name, description in skill_descriptions.items()
                ),
                item_count=len(skill_descriptions),
            )
        )
    if tool_definitions:
        sections.append(
            ContextSection(
                name="tool_catalog",
                content="Tools:\n"
                + "\n".join(
                    f"- {definition.name}: {catalog_description(definition.description)}"
                    for definition in tool_definitions
                ),
                item_count=len(tool_definitions),
            )
        )
    sections.append(ContextSection(name="memory_access_rules", content=MEMORY_ACCESS_RULES))
    if short_term_plan.agent_state:
        sections.append(
            ContextSection(
                name="agent_state",
                content="Current agent state:\n"
                + "\n".join(f"- {item.key}: {item.value}" for item in short_term_plan.agent_state),
                item_count=len(short_term_plan.agent_state),
            )
        )
    if short_term_plan.orchestration_state:
        sections.append(
            ContextSection(
                name="main_orchestration_state",
                content="Main orchestration state:\n"
                + "\n".join(
                    f"- {item.key}: {item.value} [owner_agent_id: {item.owner_agent_id}]"
                    for item in short_term_plan.orchestration_state
                ),
                item_count=len(short_term_plan.orchestration_state),
            )
        )
    context_summary_lines = format_context_summary_lines(short_term_plan.context_summaries)
    if context_summary_lines:
        sections.append(
            ContextSection(
                name="compressed_session_summary",
                content="Compressed session summary:\n" + "\n".join(context_summary_lines),
                item_count=len(context_summary_lines),
            )
        )
    if short_term_plan.assigned_tasks:
        sections.append(
            ContextSection(
                name="assigned_agent_tasks",
                content="Assigned agent tasks:\n" + "\n".join(format_assigned_task_lines(short_term_plan.assigned_tasks)),
                item_count=len(short_term_plan.assigned_tasks),
            )
        )
    if short_term_plan.child_result_summaries:
        sections.append(
            ContextSection(
                name="child_agent_result_summaries",
                content="Child agent result summaries:\n"
                + "\n".join(format_child_result_summary_lines(short_term_plan.child_result_summaries)),
                item_count=len(short_term_plan.child_result_summaries),
            )
        )
    if memory_slices.long_term_summaries or any(items for items in memory_slices.facts_by_lane.values()):
        sections.append(
            ContextSection(
                name="long_term_memory_rules",
                content=(
                    "Long-term memory: use stable summaries and high-confidence facts when relevant. "
                    "Shared entries describe cross-agent context; agent overlay entries describe this agent's view."
                ),
            )
        )
    for scope_key, items in group_memory_items_by_scope(memory_slices.long_term_summaries).items():
        if not items:
            continue
        scope_label = MEMORY_SCOPE_LABELS.get(scope_key, scope_key.replace("_", " ").title())
        sections.append(
            ContextSection(
                name=f"long_term_summaries_{section_key(scope_key)}",
                content=f"Long-term summaries - {scope_label}:\n" + "\n".join(format_memory_lines(items)),
                item_count=len(items),
            )
        )
    for lane, items in memory_slices.facts_by_lane.items():
        if not items:
            continue
        label = MEMORY_LANE_LABELS.get(lane, lane.replace("_", " ").title())
        for scope_key, scoped_items in group_memory_items_by_scope(items).items():
            if not scoped_items:
                continue
            scope_label = MEMORY_SCOPE_LABELS.get(scope_key, scope_key.replace("_", " ").title())
            sections.append(
                ContextSection(
                    name=f"long_term_facts_{section_key(scope_key)}_{lane}",
                    content=f"Long-term facts - {scope_label} / {label}:\n"
                    + "\n".join(format_memory_lines(scoped_items)),
                    item_count=len(scoped_items),
                )
            )
    if memory_slices.mid_term_items:
        sections.append(
            ContextSection(
                name="mid_term_context",
                content=(
                    "Mid-term context: use these recent daily notes as lower-confidence background. "
                    "Prefer long-term memory if they conflict.\n"
                    + "\n".join(format_memory_lines(memory_slices.mid_term_items))
                ),
                item_count=len(memory_slices.mid_term_items),
            )
        )
    if active_files:
        file_lines = [
            (
                f"- file_id={item.file_id} name={item.filename} type={item.media_type} "
                f"status={item.status} size_bytes={item.size_bytes}"
            )
            for item in active_files
        ]
        sections.append(
            ContextSection(
                name="active_files",
                content="Active session files (metadata only):\n"
                + "\n".join(file_lines)
                + "\nUse session_list_files/session_read_file/session_search_file when you need file content details.",
                item_count=len(active_files),
            )
        )
    return ContextAssemblyPlan(role=role, sections=sections)
