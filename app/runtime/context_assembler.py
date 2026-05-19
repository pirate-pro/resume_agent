"""Compose system prompt, messages, memory, and tool context."""

from __future__ import annotations

import logging
from typing import cast

from app.core.errors import StorageError
from app.core.errors import ValidationError
from app.domain.models import (
    AgentIdentityDocuments,
    ContextBundle,
    EventRecord,
    MemoryItem,
    RunContext,
    SessionArtifact,
    ToolDefinition,
)
from app.domain.protocols import AgentDocumentRepository, SessionRepository, SkillRepository, ToolExecutor
from app.runtime.context.catalog import fallback_skill_description
from app.runtime.context.constants import (
    ACTIVE_FILE_MAX_COUNT,
    AGENT_STATE_MAX_COUNT,
    AGENT_TASK_CONTEXT_MAX_COUNT,
    CHILD_RESULT_CONTEXT_MAX_COUNT,
    ORCHESTRATION_STATE_MAX_COUNT,
    RECENT_EVENT_MAX_COUNT,
)
from app.runtime.context.memory_sections import flatten_memory_lanes
from app.runtime.context.models import (
    AgentCatalogItem,
    ContextAssemblyPlan,
    ContextAssemblyRole,
    ContextSection,
    ShortTermContextPlan,
)
from app.runtime.context_compaction.text_utils import estimate_tokens_from_text
from app.runtime.agent_registry import AgentRegistry
from app.runtime.context.section_builder import build_assembly_plan
from app.runtime.context.short_term import (
    exclude_context_summaries,
    extract_assigned_tasks,
    extract_child_result_summaries,
    is_main_agent_orchestration_event,
    is_other_agent_related_event,
    latest_context_summaries,
)
from app.runtime.context.career_flow_state import extract_career_flow_state
from app.runtime.context.workflow_rules import (
    WorkflowRulePack,
    normalize_workflow_rule_selection_mode,
    select_full_workflow_skill_names,
    select_sparse_workflow_rule_packs,
)
from app.runtime.context.workflow_state import extract_current_workflow_state
from app.runtime.agent.tool_reveal import normalize_always_visible_tool_names, normalize_tool_schema_disclosure_mode
from app.runtime.memory_manager import MemoryManager
from app.state.manager import StateManager

__all__ = [
    "ContextAssembler",
    "ContextAssemblyPlan",
    "ContextAssemblyRole",
    "ContextSection",
    "ShortTermContextPlan",
]
_logger = logging.getLogger(__name__)


class ContextAssembler:
    """Build contextual bundle for one model invocation."""

    def __init__(
        self,
        session_repository: SessionRepository,
        skill_repository: SkillRepository,
        agent_document_repository: AgentDocumentRepository,
        memory_manager: MemoryManager,
        state_manager: StateManager,
        tool_executor: ToolExecutor,
        agent_registry: AgentRegistry | None = None,
        tool_schema_disclosure_mode: str = "full",
        tool_schema_always_visible: str | list[str] | None = None,
        workflow_rule_selection_mode: str = "full",
    ) -> None:
        self._session_repository = session_repository
        self._skill_repository = skill_repository
        self._agent_document_repository = agent_document_repository
        self._memory_manager = memory_manager
        self._state_manager = state_manager
        self._tool_executor = tool_executor
        self._agent_registry = agent_registry
        self._tool_schema_disclosure_mode = normalize_tool_schema_disclosure_mode(tool_schema_disclosure_mode)
        self._tool_schema_always_visible = normalize_always_visible_tool_names(tool_schema_always_visible)
        self._workflow_rule_selection_mode = normalize_workflow_rule_selection_mode(workflow_rule_selection_mode)

    @staticmethod
    def determine_role(context: RunContext) -> ContextAssemblyRole:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        if context.agent_id == context.entry_agent_id:
            return ContextAssemblyRole.MAIN_AGENT
        return ContextAssemblyRole.OTHER_AGENT

    def assemble(self, context: RunContext, user_message: str, skill_names: list[str]) -> ContextBundle:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValidationError("user_message must be a non-empty string.")
        if not isinstance(skill_names, list):
            raise ValidationError("skill_names must be a list.")

        normalized_session_id = context.session_id
        normalized_message = user_message.strip()
        assembly_role = self.determine_role(context)

        active_artifacts = self._load_active_artifacts(normalized_session_id)
        skills = self._skill_repository.load_skills(skill_names) if skill_names else {}
        workflow_rule_packs = self._load_workflow_rule_packs(
            role=assembly_role,
            user_message=normalized_message,
            active_artifacts=active_artifacts,
        )
        skill_descriptions = self._load_skill_descriptions(loaded_skills=skills)
        agent_documents = self._load_agent_documents(context)
        invokable_agents = self._load_invokable_agents(context=context, role=assembly_role)
        short_term_plan = self._build_short_term_context_plan(
            context,
            role=assembly_role,
            limit=RECENT_EVENT_MAX_COUNT,
            user_message=normalized_message,
        )
        memory_hits, memory_summary, memory_lanes = self._safe_memory_search(
            normalized_message,
            limit=5,
            context=context,
        )
        messages = self._build_messages_from_events(short_term_plan.recent_events)
        # 用户当前这条输入必须进入模型消息，否则会出现“模型只看历史不看当前”的问题。
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != normalized_message:
            messages.append({"role": "user", "content": normalized_message})

        available_tool_definitions = self._list_tool_definitions(context.agent_id)
        tool_definitions = available_tool_definitions
        if self._uses_search_disclosure(context=context, role=assembly_role):
            prompt_tool_definitions = [
                definition
                for definition in available_tool_definitions
                if definition.name in set(self._tool_schema_always_visible)
            ]
        else:
            # Full mode is an explicit debugging and rollback path: expose all
            # capability-allowed schemas instead of maintaining a second
            # intent-based selection mechanism alongside tool_search.
            prompt_tool_definitions = tool_definitions
        assembly_plan = build_assembly_plan(
            role=assembly_role,
            skill_descriptions=skill_descriptions,
            workflow_rule_packs=workflow_rule_packs,
            tool_definitions=prompt_tool_definitions,
            agent_documents=agent_documents,
            invokable_agents=invokable_agents,
            short_term_plan=short_term_plan,
            memory_lanes=memory_lanes,
            active_artifacts=active_artifacts,
        )
        system_prompt = assembly_plan.render_prompt()
        _logger.debug(
            "上下文组装: session_id=%s role=%s sections=%s skills=%s workflow_packs=%s has_agent_md=%s has_soul_md=%s invokable_agents=%s agent_state=%s orchestration_state=%s workflow_state=%s career_flow_state=%s assigned_tasks=%s child_results=%s memory_hits=%s active_artifacts=%s recent_events=%s output_messages=%s",
            normalized_session_id,
            assembly_plan.role.value,
            assembly_plan.section_names(),
            len(skills),
            len(workflow_rule_packs),
            bool(agent_documents.agent_markdown),
            bool(agent_documents.soul_markdown),
            len(invokable_agents),
            len(short_term_plan.agent_state),
            len(short_term_plan.orchestration_state),
            len(short_term_plan.workflow_state.refs),
            len(short_term_plan.career_flow_state.completed_steps),
            len(short_term_plan.assigned_tasks),
            len(short_term_plan.child_result_summaries),
            len(memory_hits),
            len(active_artifacts),
            len(short_term_plan.recent_events),
            len(messages),
        )
        return ContextBundle(
            system_prompt=system_prompt,
            messages=messages,
            memory_hits=memory_hits,
            tool_definitions=tool_definitions,
            memory_summary=memory_summary,
            memory_lanes=memory_lanes,
            system_prompt_sections=_system_prompt_section_usage(
                assembly_plan,
                workflow_rule_selection_mode=self._workflow_rule_selection_mode,
            ),
        )

    def _load_skill_descriptions(self, *, loaded_skills: dict[str, str]) -> dict[str, str]:
        if not loaded_skills:
            return {}
        descriptions: dict[str, str] = {}
        list_skills = getattr(self._skill_repository, "list_skills", None)
        if callable(list_skills):
            try:
                for summary in list_skills():
                    name = str(getattr(summary, "name", "")).strip()
                    description = str(getattr(summary, "description", "")).strip()
                    if name and description:
                        descriptions[name] = description
            except (StorageError, ValidationError) as exc:
                _logger.warning("Skill catalog description loading failed, using fallback: error=%s", exc)

        output: dict[str, str] = {}
        for name in loaded_skills:
            resolved_description = descriptions.get(name)
            if resolved_description is None:
                resolved_description = fallback_skill_description(name=name, instructions=loaded_skills[name])
            output[name] = resolved_description
        return output

    def _uses_search_disclosure(self, *, context: RunContext, role: ContextAssemblyRole) -> bool:
        return (
            self._tool_schema_disclosure_mode == "search"
            and context.agent_id == "agent_main"
            and role == ContextAssemblyRole.MAIN_AGENT
        )

    def _load_workflow_rule_packs(
        self,
        *,
        role: ContextAssemblyRole,
        user_message: str,
        active_artifacts: list[SessionArtifact],
    ) -> list[WorkflowRulePack]:
        if self._workflow_rule_selection_mode == "sparse":
            return select_sparse_workflow_rule_packs(
                role=role,
                user_message=user_message,
                active_artifacts=active_artifacts,
            )

        skill_names = select_full_workflow_skill_names(
            role=role,
            user_message=user_message,
            active_artifacts=active_artifacts,
        )
        if not skill_names:
            return []
        try:
            skills = self._skill_repository.load_skills(skill_names)
        except (StorageError, ValidationError) as exc:
            _logger.warning("Workflow skill loading failed, skipped: skills=%s error=%s", skill_names, exc)
            return []
        return [
            WorkflowRulePack(
                name=name,
                title=name,
                content=skills[name],
            )
            for name in skill_names
            if name in skills
        ]

    def _load_agent_documents(self, context: RunContext) -> AgentIdentityDocuments:
        try:
            return self._agent_document_repository.load_documents(context.agent_id)
        except (StorageError, ValidationError) as exc:
            _logger.warning(
                "AGENT/SOUL 文档加载失败，跳过静态身份注入: agent_id=%s error=%s",
                context.agent_id,
                exc,
            )
        return AgentIdentityDocuments()

    def _load_invokable_agents(self, *, context: RunContext, role: ContextAssemblyRole) -> list[AgentCatalogItem]:
        if role != ContextAssemblyRole.MAIN_AGENT or self._agent_registry is None:
            return []
        try:
            return [
                AgentCatalogItem(
                    agent_id=definition.agent_id,
                    display_name=definition.display_name,
                    role=definition.role,
                    description=definition.description,
                )
                for definition in self._agent_registry.list_agents(enabled_only=True)
                if definition.agent_id != context.agent_id
                and self._agent_registry.can_invoke(context.agent_id, definition.agent_id)
            ]
        except ValidationError as exc:
            _logger.warning("可调用 agent 目录加载失败，跳过注入: agent_id=%s error=%s", context.agent_id, exc)
            return []

    def _list_tool_definitions(self, agent_id: str) -> list[ToolDefinition]:
        list_for_agent = getattr(self._tool_executor, "list_definitions_for_agent", None)
        if callable(list_for_agent):
            try:
                return cast(list[ToolDefinition], list_for_agent(agent_id))
            except ValidationError as exc:
                _logger.warning("工具目录按 agent 过滤失败，回退到完整目录: agent_id=%s error=%s", agent_id, exc)
        return self._tool_executor.list_definitions()

    def _build_short_term_context_plan(
        self,
        context: RunContext,
        *,
        role: ContextAssemblyRole,
        limit: int,
        user_message: str,
    ) -> ShortTermContextPlan:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        agent_state = self._state_manager.list_agent_state(
            session_id=context.session_id,
            agent_id=context.agent_id,
        )[:AGENT_STATE_MAX_COUNT]

        if role == ContextAssemblyRole.MAIN_AGENT:
            orchestration_state = self._state_manager.list_shared_state(session_id=context.session_id)[
                :ORCHESTRATION_STATE_MAX_COUNT
            ]
            agent_events = self._session_repository.list_agent_events(context.session_id, context.agent_id)
            orchestration_events = self._session_repository.list_orchestration_events(context.session_id)
            main_view_events = _merge_context_events(agent_events, orchestration_events)
            visible_events = [event for event in main_view_events if is_main_agent_orchestration_event(event, context)]
            workflow_state = extract_current_workflow_state(visible_events, context)
            career_flow_state = extract_career_flow_state(
                visible_events,
                context,
                user_message=user_message,
                workflow_state=workflow_state,
            )
            context_summaries = latest_context_summaries(visible_events, context)
            recent_events = exclude_context_summaries(visible_events)[-limit:]
            child_result_summaries = extract_child_result_summaries(recent_events, context)[
                -CHILD_RESULT_CONTEXT_MAX_COUNT:
            ]
            assigned_tasks = []
        else:
            # Other agents keep a local execution view. Main-agent orchestration state is passed via task events.
            orchestration_state = []
            agent_events = self._session_repository.list_agent_events(context.session_id, context.agent_id)
            orchestration_events = self._session_repository.list_orchestration_events(context.session_id)
            all_events = _merge_context_events(agent_events, orchestration_events)
            related_events = [event for event in agent_events if is_other_agent_related_event(event, context)]
            context_summaries = latest_context_summaries(related_events, context)
            recent_events = exclude_context_summaries(related_events)[-limit:]
            assigned_tasks = extract_assigned_tasks(all_events, context)[-AGENT_TASK_CONTEXT_MAX_COUNT:]
            child_result_summaries = []
            workflow_state = extract_current_workflow_state(related_events, context)
            career_flow_state = extract_career_flow_state(
                related_events,
                context,
                user_message=user_message,
                workflow_state=workflow_state,
            )

        return ShortTermContextPlan(
            role=role,
            agent_state=agent_state,
            orchestration_state=orchestration_state,
            recent_events=recent_events,
            context_summaries=context_summaries,
            assigned_tasks=assigned_tasks,
            child_result_summaries=child_result_summaries,
            workflow_state=workflow_state,
            career_flow_state=career_flow_state,
        )

    def _safe_memory_search(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryItem], dict[str, str | int | bool | list[str] | dict[str, int]], dict[str, list[MemoryItem]]]:
        try:
            lanes, summary = self._memory_manager.search_context_memory_lanes(
                query=query,
                limit=limit,
                context=context,
            )
            hits = flatten_memory_lanes(lanes)
            normalized_summary: dict[str, str | int | bool | list[str] | dict[str, int]] = {
                "query": str(summary.get("query", "")),
                "agent_id": str(summary.get("agent_id", "")),
                "session_id": str(summary.get("session_id", "")),
                "hit_count": int(summary.get("hit_count", 0)),
                "total_scanned": int(summary.get("total_scanned", 0)),
                "truncated": bool(summary.get("truncated", False)),
                "searched_scopes": [str(item) for item in summary.get("searched_scopes", [])],
                "notes": [str(item) for item in summary.get("notes", [])],
            }
            raw_lanes = summary.get("lanes", {})
            if isinstance(raw_lanes, dict):
                normalized_summary["lanes"] = {
                    str(key): int(value)
                    for key, value in raw_lanes.items()
                    if isinstance(value, int)
                }
            return hits, normalized_summary, lanes
        except ValidationError as exc:
            _logger.warning("记忆检索参数不合法，跳过检索: query=%s limit=%s error=%s", query, limit, exc)
            return [], {
                "query": query,
                "agent_id": context.agent_id,
                "session_id": context.session_id,
                "hit_count": 0,
                "total_scanned": 0,
                "truncated": False,
                "searched_scopes": [],
                "notes": [f"validation_error: {exc}"],
            }, {}

    def _build_messages_from_events(self, events: list[EventRecord]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for event in events:
            if event.type == "user_message":
                content = str(event.payload.get("content", "")).strip()
                if content:
                    messages.append({"role": "user", "content": content})
            elif event.type == "assistant_message":
                content = str(event.payload.get("content", "")).strip()
                if content:
                    messages.append({"role": "assistant", "content": content})
        return messages

    def _load_active_artifacts(self, session_id: str) -> list[SessionArtifact]:
        artifacts = self._session_repository.list_session_artifacts(session_id)
        active_ids = self._session_repository.get_active_artifact_ids(session_id)
        artifact_map = {item.artifact_id: item for item in artifacts}

        output: list[SessionArtifact] = []
        for artifact_id in active_ids:
            item = artifact_map.get(artifact_id)
            if item is None:
                continue
            output.append(item)
            if len(output) >= ACTIVE_FILE_MAX_COUNT:
                break
        return output


def _merge_context_events(*event_groups: list[EventRecord]) -> list[EventRecord]:
    by_id: dict[str, EventRecord] = {}
    for group in event_groups:
        for event in group:
            by_id.setdefault(event.event_id, event)
    return sorted(by_id.values(), key=lambda item: item.created_at)


def _system_prompt_section_usage(
    assembly_plan: ContextAssemblyPlan,
    *,
    workflow_rule_selection_mode: str,
) -> list[dict[str, int | str | list[str]]]:
    output: list[dict[str, int | str | list[str]]] = []
    for section in assembly_plan.sections:
        item: dict[str, int | str | list[str]] = {
            "name": section.name,
            "tokens": estimate_tokens_from_text(section.content),
            "chars": len(section.content),
            "item_count": section.item_count,
        }
        if section.name == "workflow_rules":
            pack_names = section.metadata.get("pack_names")
            if isinstance(pack_names, list):
                item["pack_names"] = [str(name) for name in pack_names if str(name).strip()]
            item["selection_mode"] = workflow_rule_selection_mode
        output.append(item)
    return output
