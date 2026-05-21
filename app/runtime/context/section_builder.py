"""Prompt section builder for context assembly."""

from __future__ import annotations

from app.domain.models import AgentIdentityDocuments, MemoryItem, SessionArtifact, ToolDefinition
from app.runtime.context.catalog import render_compact_search_tool_catalog, render_full_tool_catalog
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
from app.runtime.context.models import AgentCatalogItem
from app.runtime.context.short_term import (
    format_assigned_task_lines,
    format_child_result_summary_lines,
    format_context_summary_lines,
)
from app.runtime.context.career_flow_state import format_career_flow_state_lines
from app.runtime.context.workflow_rules import WorkflowRulePack
from app.runtime.context.workflow_state import format_current_workflow_state_lines
from app.runtime.workflow.phase import format_workflow_phase_lines
from app.runtime.workflow.tool_plan import format_runtime_tool_plan_lines


def build_assembly_plan(
    *,
    role: ContextAssemblyRole,
    skill_descriptions: dict[str, str],
    workflow_rule_packs: list[WorkflowRulePack],
    tool_definitions: list[ToolDefinition],
    agent_documents: AgentIdentityDocuments,
    invokable_agents: list[AgentCatalogItem],
    short_term_plan: ShortTermContextPlan,
    memory_lanes: dict[str, list[MemoryItem]],
    active_artifacts: list[SessionArtifact],
    tool_catalog_mode: str = "full",
    visible_tool_names: list[str] | None = None,
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
        tool_catalog_content = (
            render_compact_search_tool_catalog(
                tool_definitions,
                visible_tool_names=visible_tool_names or [],
            )
            if tool_catalog_mode == "compact_search"
            else render_full_tool_catalog(tool_definitions)
        )
        sections.append(
            ContextSection(
                name="tool_catalog",
                content=tool_catalog_content,
                item_count=len(tool_definitions),
                metadata={"catalog_mode": tool_catalog_mode},
            )
        )
    if workflow_rule_packs:
        sections.append(
            ContextSection(
                name="workflow_rules",
                content="Selected workflow rules:\n\n"
                + "\n\n".join(f"## {pack.title}\n{pack.content}" for pack in workflow_rule_packs),
                item_count=len(workflow_rule_packs),
                metadata={"pack_names": [pack.name for pack in workflow_rule_packs]},
            )
        )
    if role == ContextAssemblyRole.MAIN_AGENT and invokable_agents:
        sections.append(
            ContextSection(
                name="available_child_agents",
                content=(
                    "Available child agents for delegation:\n"
                    + "\n".join(format_agent_catalog_lines(invokable_agents))
                    + "\n\nDelegation rules:\n"
                    "- If the user's task clearly matches a listed child agent's role, you must call delegate_agents before finalizing the answer.\n"
                    "- Do not directly complete specialized child-agent work yourself when a matching child agent is available.\n"
                    "- If delegate_agents has already returned completed results for the same subtask in this run, do not delegate that same subtask again; use the returned ids/artifacts.\n"
                    "- A single specialized task is enough reason to delegate; delegation is not limited to multi-step tasks.\n"
                    "- Delegate one or more subtasks when they clearly match a child agent's role.\n"
                    "- Put multiple independent subtasks in one delegate_agents call so they can run concurrently.\n"
                    "- Do not delegate tasks with unresolved sequential dependencies; resolve prerequisites first.\n"
                    "- Do not pass depends_on to delegate_agents; this version only supports independent child tasks.\n"
                    "- Child agent ids such as resume_agent/job_agent are not tool names; never call them directly. Use delegate_agents with tasks[].target_agent_id.\n"
                    "- Use max_tool_rounds 10-20 for child tasks that must create artifacts or product records.\n"
                    "- Product record ids must come from tool results, child-agent results, or list tools; do not invent ids.\n"
                    "- Keep each child instruction narrow, include constraints, and pass artifact_refs when shared artifacts matter.\n"
                    "- If the source material is pasted in the current user message, include the relevant source text directly in the child instruction.\n"
                    "- Do not create workspace files only to pass their paths to child agents; artifact_refs must be current session artifact ids.\n"
                    "- After child results return, synthesize the final answer yourself; do not expose raw orchestration noise."
                ),
                item_count=len(invokable_agents),
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
    workflow_state_lines = format_current_workflow_state_lines(short_term_plan.workflow_state)
    if workflow_state_lines:
        sections.append(
            ContextSection(
                name="current_workflow_state",
                content=(
                    "Current workflow state from successful tool results:\n"
                    + "\n".join(workflow_state_lines)
                    + "\n\nUse these ids directly for follow-up get/read/update calls. "
                    "Call list tools only when an id is missing or the user asks to enumerate records."
                ),
                item_count=len(workflow_state_lines),
            )
        )
    career_flow_state_lines = format_career_flow_state_lines(short_term_plan.career_flow_state)
    if career_flow_state_lines:
        sections.append(
            ContextSection(
                name="current_career_flow_state",
                content=(
                    "Current career flow state from deterministic runtime facts:\n"
                    + "\n".join(career_flow_state_lines)
                    + "\n\nUse confirmed ids directly. Do not repeat tools listed in do_not_repeat. "
                    "If final_answer_ready=true, stop calling tools and produce the final user-facing answer."
                ),
                item_count=len(career_flow_state_lines),
            )
        )
    workflow_phase_lines = format_workflow_phase_lines(short_term_plan.workflow_phase)
    if workflow_phase_lines:
        sections.append(
            ContextSection(
                name="current_workflow_phase",
                content=(
                    "Current workflow phase guard snapshot:\n"
                    + "\n".join(workflow_phase_lines)
                    + "\n\nTreat missing_outputs as product gaps, not narrative gaps. "
                    "Do not call tools listed in blocked_tool_names unless the user explicitly asks to restart or create another version."
                ),
                item_count=len(workflow_phase_lines),
            )
        )
    runtime_tool_plan_lines = format_runtime_tool_plan_lines(short_term_plan.runtime_tool_plan)
    if runtime_tool_plan_lines:
        sections.append(
            ContextSection(
                name="current_runtime_tool_plan",
                content=(
                    "Runtime tool plan for this model round:\n"
                    + "\n".join(runtime_tool_plan_lines)
                    + "\n\nIf next_allowed_tools is non-empty, call only those tools for the next step. "
                    "Do not call tool_search again for the same step. "
                    "If final_answer_ready=true, stop tool calls and answer the user."
                ),
                item_count=len(runtime_tool_plan_lines),
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
    if active_artifacts:
        artifact_lines = [
            (
                f"- artifact_id={item.artifact_id} title={item.title} kind={item.kind} type={item.media_type} "
                f"status={item.status} visibility={item.visibility} size_bytes={item.size_bytes}"
            )
            for item in active_artifacts
        ]
        sections.append(
            ContextSection(
                name="active_artifacts",
                content="Active session artifacts (metadata only):\n"
                + "\n".join(artifact_lines)
                + "\nUse session_list_artifacts/session_read_artifact/session_search_artifact when you need artifact content details.",
                item_count=len(active_artifacts),
            )
        )
    return ContextAssemblyPlan(role=role, sections=sections)


def format_agent_catalog_lines(agents: list[AgentCatalogItem]) -> list[str]:
    return [
        (
            f"- agent_id={agent.agent_id} name={agent.display_name} "
            f"role={agent.role} description={agent.description}"
        )
        for agent in agents
    ]
