"""Compose system prompt, messages, memory, and tool context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from app.core.errors import StorageError
from app.core.errors import ValidationError
from app.domain.models import (
    AgentIdentityDocuments,
    ContextBundle,
    EventRecord,
    MemoryItem,
    RunContext,
    SessionFile,
    ToolDefinition,
)
from app.domain.protocols import AgentDocumentRepository, SessionRepository, SkillRepository, ToolExecutor
from app.memory.policies import MemoryLane
from app.runtime.agent_events import (
    AGENT_RESULT_SUMMARY_EVENT,
    AGENT_TASK_ASSIGNED_EVENT,
    AgentResultSummaryPayload,
    AgentTaskAssignedPayload,
)
from app.runtime.context_compactor import CONTEXT_SUMMARY_EVENT
from app.runtime.memory_manager import MemoryManager
from app.state.manager import StateManager
from app.state.models import StateRecord

__all__ = [
    "ContextAssembler",
    "ContextAssemblyPlan",
    "ContextAssemblyRole",
    "ContextSection",
    "ShortTermContextPlan",
]
_logger = logging.getLogger(__name__)
_ACTIVE_FILE_MAX_COUNT = 12
_AGENT_STATE_MAX_COUNT = 8
_ORCHESTRATION_STATE_MAX_COUNT = 8
_RECENT_EVENT_MAX_COUNT = 12
_AGENT_TASK_CONTEXT_MAX_COUNT = 8
_CHILD_RESULT_CONTEXT_MAX_COUNT = 8
_MEMORY_LANE_LABELS = {
    MemoryLane.IDENTITY.value: "Identity",
    MemoryLane.RESPONSE_PREFERENCES.value: "Response preferences",
    MemoryLane.INTERACTION_FEEDBACK.value: "Interaction feedback",
    MemoryLane.USER_PROFILE.value: "User profile",
    MemoryLane.OTHER_MEMORIES.value: "Other relevant memory",
}
_MEMORY_SCOPE_LABELS = {
    "shared_long": "Shared",
    "agent_long": "Agent overlay",
    "agent_short": "Agent short",
    "shared": "Shared",
    "agent": "Agent overlay",
    "unknown": "Unknown scope",
}
_OUTPUT_FORMAT_RULES = """Answer output rules:
1. Answer directly and keep the structure no heavier than the task needs.
2. Use Markdown naturally; do not wrap an entire Markdown document in a fenced block unless the user asks for source.
3. Use fenced code blocks with language labels for code.
4. If a file was created or read and the user asks for content, include the actual content or the exact file path.
5. Use tables only when rows/columns make comparison clearer.
6. Use emphasis sparingly; never bold whole paragraphs.
7. If information is missing, say what is unknown instead of inventing details."""
_MEMORY_ACCESS_RULES = """Memory access rules:
1. Treat session events and state as short-term working context, not durable memory.
2. Use shared memory for cross-agent stable context and the current agent overlay for agent-specific observations.
3. Do not assume private memory from other agents is visible unless the runtime provides it.
4. Prefer high-confidence facts and long-term summaries over mid-term notes when they conflict.
5. If a relevant long-term fact is already included in this context, answer from it directly; do not call memory_search just to verify it."""


class ContextAssemblyRole(str, Enum):
    MAIN_AGENT = "main_agent"
    OTHER_AGENT = "other_agent"


@dataclass(slots=True)
class ContextSection:
    """One renderable prompt section with a stable internal name."""

    name: str
    content: str
    item_count: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("section name must be a non-empty string.")
        self.name = self.name.strip()
        if not isinstance(self.content, str) or not self.content.strip():
            raise ValidationError("section content must be a non-empty string.")
        if self.item_count < 0:
            raise ValidationError("section item_count cannot be negative.")


@dataclass(slots=True)
class ContextAssemblyPlan:
    """Role-aware section plan for one model invocation."""

    role: ContextAssemblyRole
    sections: list[ContextSection]

    def __post_init__(self) -> None:
        if not isinstance(self.role, ContextAssemblyRole):
            raise ValidationError("role must be ContextAssemblyRole.")
        if not isinstance(self.sections, list):
            raise ValidationError("sections must be a list.")

    def render_prompt(self) -> str:
        return "\n\n".join(section.content for section in self.sections)

    def section_names(self) -> list[str]:
        return [section.name for section in self.sections]

    def summary(self) -> dict[str, int | str | list[str]]:
        return {
            "role": self.role.value,
            "section_count": len(self.sections),
            "sections": self.section_names(),
        }


@dataclass(slots=True)
class ShortTermContextPlan:
    """Role-aware short-term context selected for one invocation."""

    role: ContextAssemblyRole
    agent_state: list[StateRecord]
    orchestration_state: list[StateRecord]
    recent_events: list[EventRecord]
    context_summaries: list[EventRecord]
    assigned_tasks: list[AgentTaskAssignedPayload]
    child_result_summaries: list[AgentResultSummaryPayload]

    def __post_init__(self) -> None:
        if not isinstance(self.role, ContextAssemblyRole):
            raise ValidationError("short-term role must be ContextAssemblyRole.")
        if not isinstance(self.agent_state, list):
            raise ValidationError("agent_state must be a list.")
        if not isinstance(self.orchestration_state, list):
            raise ValidationError("orchestration_state must be a list.")
        if not isinstance(self.recent_events, list):
            raise ValidationError("recent_events must be a list.")
        if not isinstance(self.context_summaries, list):
            raise ValidationError("context_summaries must be a list.")
        if not isinstance(self.assigned_tasks, list):
            raise ValidationError("assigned_tasks must be a list.")
        if not isinstance(self.child_result_summaries, list):
            raise ValidationError("child_result_summaries must be a list.")


@dataclass(slots=True)
class _MemoryContextSlices:
    long_term_summaries: list[MemoryItem]
    facts_by_lane: dict[str, list[MemoryItem]]
    mid_term_items: list[MemoryItem]


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
    ) -> None:
        self._session_repository = session_repository
        self._skill_repository = skill_repository
        self._agent_document_repository = agent_document_repository
        self._memory_manager = memory_manager
        self._state_manager = state_manager
        self._tool_executor = tool_executor

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

        skills = self._skill_repository.load_skills(skill_names) if skill_names else {}
        skill_descriptions = self._load_skill_descriptions(loaded_skills=skills)
        agent_documents = self._load_agent_documents(context)
        short_term_plan = self._build_short_term_context_plan(
            context,
            role=assembly_role,
            limit=_RECENT_EVENT_MAX_COUNT,
        )
        memory_hits, memory_summary, memory_lanes = self._safe_memory_search(
            normalized_message,
            limit=5,
            context=context,
        )
        active_files = self._load_active_files(normalized_session_id)
        messages = self._build_messages_from_events(short_term_plan.recent_events)
        # 用户当前这条输入必须进入模型消息，否则会出现“模型只看历史不看当前”的问题。
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != normalized_message:
            messages.append({"role": "user", "content": normalized_message})

        tool_definitions = self._tool_executor.list_definitions()
        assembly_plan = self._build_assembly_plan(
            role=assembly_role,
            skill_descriptions=skill_descriptions,
            tool_definitions=tool_definitions,
            agent_documents=agent_documents,
            short_term_plan=short_term_plan,
            memory_lanes=memory_lanes,
            active_files=active_files,
        )
        system_prompt = assembly_plan.render_prompt()
        _logger.debug(
            "上下文组装: session_id=%s role=%s sections=%s skills=%s has_agent_md=%s has_soul_md=%s agent_state=%s orchestration_state=%s assigned_tasks=%s child_results=%s memory_hits=%s active_files=%s recent_events=%s output_messages=%s",
            normalized_session_id,
            assembly_plan.role.value,
            assembly_plan.section_names(),
            len(skills),
            bool(agent_documents.agent_markdown),
            bool(agent_documents.soul_markdown),
            len(short_term_plan.agent_state),
            len(short_term_plan.orchestration_state),
            len(short_term_plan.assigned_tasks),
            len(short_term_plan.child_result_summaries),
            len(memory_hits),
            len(active_files),
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
                resolved_description = _fallback_skill_description(name=name, instructions=loaded_skills[name])
            output[name] = resolved_description
        return output

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

    def _build_short_term_context_plan(
        self,
        context: RunContext,
        *,
        role: ContextAssemblyRole,
        limit: int,
    ) -> ShortTermContextPlan:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        agent_state = self._state_manager.list_agent_state(
            session_id=context.session_id,
            agent_id=context.agent_id,
        )[:_AGENT_STATE_MAX_COUNT]

        if role == ContextAssemblyRole.MAIN_AGENT:
            orchestration_state = self._state_manager.list_shared_state(session_id=context.session_id)[
                :_ORCHESTRATION_STATE_MAX_COUNT
            ]
            all_events = self._session_repository.list_events(context.session_id)
            context_summaries = _latest_context_summaries(all_events, context)
            recent_events = _exclude_context_summaries(all_events)[-limit:]
            child_result_summaries = _extract_child_result_summaries(recent_events, context)[
                -_CHILD_RESULT_CONTEXT_MAX_COUNT:
            ]
            assigned_tasks: list[AgentTaskAssignedPayload] = []
        else:
            # Other agents keep a local execution view. Main-agent orchestration state is passed via task events.
            orchestration_state = []
            all_events = self._session_repository.list_events(context.session_id)
            related_events = [event for event in all_events if _is_other_agent_related_event(event, context)]
            context_summaries = _latest_context_summaries(related_events, context)
            recent_events = _exclude_context_summaries(related_events)[-limit:]
            assigned_tasks = _extract_assigned_tasks(all_events, context)[-_AGENT_TASK_CONTEXT_MAX_COUNT:]
            child_result_summaries = []

        return ShortTermContextPlan(
            role=role,
            agent_state=agent_state,
            orchestration_state=orchestration_state,
            recent_events=recent_events,
            context_summaries=context_summaries,
            assigned_tasks=assigned_tasks,
            child_result_summaries=child_result_summaries,
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
            hits = _flatten_memory_lanes(lanes)
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

    def _build_assembly_plan(
        self,
        *,
        role: ContextAssemblyRole,
        skill_descriptions: dict[str, str],
        tool_definitions: list[ToolDefinition],
        agent_documents: AgentIdentityDocuments,
        short_term_plan: ShortTermContextPlan,
        memory_lanes: dict[str, list[MemoryItem]],
        active_files: list[SessionFile],
    ) -> ContextAssemblyPlan:
        memory_slices = _split_memory_lanes(memory_lanes)
        sections: list[ContextSection] = [
            ContextSection(
                name="runtime_base",
                content="You are a pragmatic assistant. Use tools when needed and never fabricate tool results.",
            ),
            ContextSection(
                name="unknown_information_policy",
                content="If information is unknown, say you do not know.",
            ),
            ContextSection(name="output_format_rules", content=_OUTPUT_FORMAT_RULES),
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
                        f"- {definition.name}: {_catalog_description(definition.description)}"
                        for definition in tool_definitions
                    ),
                    item_count=len(tool_definitions),
                )
            )
        sections.append(ContextSection(name="memory_access_rules", content=_MEMORY_ACCESS_RULES))
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
        context_summary_lines = _format_context_summary_lines(short_term_plan.context_summaries)
        if context_summary_lines:
            sections.append(
                ContextSection(
                    name="compressed_session_summary",
                    content="Compressed session summary:\n"
                    + "\n".join(context_summary_lines),
                    item_count=len(context_summary_lines),
                )
            )
        if short_term_plan.assigned_tasks:
            sections.append(
                ContextSection(
                    name="assigned_agent_tasks",
                    content="Assigned agent tasks:\n"
                    + "\n".join(_format_assigned_task_lines(short_term_plan.assigned_tasks)),
                    item_count=len(short_term_plan.assigned_tasks),
                )
            )
        if short_term_plan.child_result_summaries:
            sections.append(
                ContextSection(
                    name="child_agent_result_summaries",
                    content="Child agent result summaries:\n"
                    + "\n".join(_format_child_result_summary_lines(short_term_plan.child_result_summaries)),
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
        for scope_key, items in _group_memory_items_by_scope(memory_slices.long_term_summaries).items():
            if not items:
                continue
            scope_label = _MEMORY_SCOPE_LABELS.get(scope_key, scope_key.replace("_", " ").title())
            sections.append(
                ContextSection(
                    name=f"long_term_summaries_{_section_key(scope_key)}",
                    content=f"Long-term summaries - {scope_label}:\n" + "\n".join(_format_memory_lines(items)),
                    item_count=len(items),
                )
            )
        for lane, items in memory_slices.facts_by_lane.items():
            if not items:
                continue
            label = _MEMORY_LANE_LABELS.get(lane, lane.replace("_", " ").title())
            for scope_key, scoped_items in _group_memory_items_by_scope(items).items():
                if not scoped_items:
                    continue
                scope_label = _MEMORY_SCOPE_LABELS.get(scope_key, scope_key.replace("_", " ").title())
                sections.append(
                    ContextSection(
                        name=f"long_term_facts_{_section_key(scope_key)}_{lane}",
                        content=f"Long-term facts - {scope_label} / {label}:\n"
                        + "\n".join(_format_memory_lines(scoped_items)),
                        item_count=len(scoped_items),
                    )
                )
        if memory_slices.mid_term_items:
            sections.append(
                ContextSection(
                    name="mid_term_context",
                    content=(
                        "Mid-term context: use these recent rolling/daily notes as lower-confidence background. "
                        "Prefer long-term memory if they conflict.\n"
                        + "\n".join(_format_memory_lines(memory_slices.mid_term_items))
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

    def _load_active_files(self, session_id: str) -> list[SessionFile]:
        files = self._session_repository.list_session_files(session_id)
        active_ids = self._session_repository.get_active_file_ids(session_id)
        file_map = {item.file_id: item for item in files}

        output: list[SessionFile] = []
        for file_id in active_ids:
            item = file_map.get(file_id)
            if item is None:
                continue
            output.append(item)
            if len(output) >= _ACTIVE_FILE_MAX_COUNT:
                break
        return output


def _flatten_memory_lanes(lanes: dict[str, list[MemoryItem]]) -> list[MemoryItem]:
    flattened: list[MemoryItem] = []
    seen: set[str] = set()
    for items in lanes.values():
        for item in items:
            if item.memory_id in seen:
                continue
            seen.add(item.memory_id)
            flattened.append(item)
    return flattened


def _split_memory_lanes(
    memory_lanes: dict[str, list[MemoryItem]],
) -> _MemoryContextSlices:
    long_term_summaries: list[MemoryItem] = []
    facts_by_lane: dict[str, list[MemoryItem]] = {}
    mid_term_items: list[MemoryItem] = []
    for lane, items in memory_lanes.items():
        for item in items:
            layer = _memory_layer(item)
            if layer == "mid_term":
                mid_term_items.append(item)
                continue
            if layer == "long_term":
                long_term_summaries.append(item)
                continue
            facts_by_lane.setdefault(lane, []).append(item)
    return _MemoryContextSlices(
        long_term_summaries=_dedupe_memory_items(long_term_summaries),
        facts_by_lane={lane: _dedupe_memory_items(items) for lane, items in facts_by_lane.items()},
        mid_term_items=_dedupe_memory_items(mid_term_items),
    )


def _memory_layer(item: MemoryItem) -> str:
    raw_layer = item.memory_layer or item.metadata.get("memory_layer")
    layer = raw_layer.strip().lower() if isinstance(raw_layer, str) else ""
    if layer:
        return layer
    tags = {tag.strip().lower() for tag in item.tags}
    source_kind = item.source_kind.strip().lower() if isinstance(item.source_kind, str) else ""
    if "mid_term" in tags or item.memory_id.startswith("mid_"):
        return "mid_term"
    if "long_term" in tags and (source_kind == "long_term_summary" or item.memory_id.startswith("long_")):
        return "long_term"
    return "facts"


def _group_memory_items_by_scope(items: list[MemoryItem]) -> dict[str, list[MemoryItem]]:
    grouped: dict[str, list[MemoryItem]] = {}
    for item in items:
        scope_key = _memory_scope_key(item)
        grouped.setdefault(scope_key, []).append(item)
    return grouped


def _memory_scope_key(item: MemoryItem) -> str:
    if item.scope:
        return item.scope.strip().lower()
    raw_scope = item.metadata.get("memory_scope") or item.metadata.get("v3_scope")
    if isinstance(raw_scope, str) and raw_scope.strip():
        return raw_scope.strip().lower()
    return "unknown"


def _format_memory_lines(items: list[MemoryItem]) -> list[str]:
    return [_format_memory_line(item) for item in items]


def _format_memory_line(item: MemoryItem) -> str:
    meta_parts: list[str] = []
    if item.scope:
        meta_parts.append(f"scope: {item.scope}")
    if item.tags:
        meta_parts.append(f"tags: {', '.join(item.tags)}")
    suffix = f" [{'; '.join(meta_parts)}]" if meta_parts else ""
    return f"- ({item.memory_id}) {item.content}{suffix}"


def _latest_context_summaries(events: list[EventRecord], context: RunContext) -> list[EventRecord]:
    summaries = [
        event
        for event in events
        if event.type == CONTEXT_SUMMARY_EVENT
        and (event.agent_id == context.agent_id or context.agent_id == context.entry_agent_id)
    ]
    return summaries[-2:]


def _exclude_context_summaries(events: list[EventRecord]) -> list[EventRecord]:
    return [event for event in events if event.type != CONTEXT_SUMMARY_EVENT]


def _format_context_summary_lines(events: list[EventRecord]) -> list[str]:
    lines: list[str] = []
    for event in events:
        raw_summary = event.payload.get("summary") or event.payload.get("content")
        summary = str(raw_summary).strip() if raw_summary is not None else ""
        if not summary:
            continue
        compressed_count = event.payload.get("compressed_event_count")
        retained_count = event.payload.get("retained_event_count")
        lines.append(
            f"- ({event.event_id}) {summary} "
            f"[compressed_events={compressed_count}; retained_events={retained_count}]"
        )
    return lines


def _section_key(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or "unknown"


def _dedupe_memory_items(items: list[MemoryItem]) -> list[MemoryItem]:
    output: list[MemoryItem] = []
    seen: set[str] = set()
    for item in items:
        if item.memory_id in seen:
            continue
        seen.add(item.memory_id)
        output.append(item)
    return output


def _fallback_skill_description(*, name: str, instructions: str) -> str:
    for raw_line in instructions.splitlines():
        line = raw_line.strip().lstrip("#").strip()
        if not line:
            continue
        if line.startswith("-"):
            line = line.lstrip("-").strip()
        if line:
            return line[:240]
    return f"Loaded skill: {name}"


def _catalog_description(description: str, *, max_chars: int = 140) -> str:
    normalized = " ".join(description.strip().split())
    if not normalized:
        return "No description."
    first_sentence = normalized.split(". ", 1)[0].rstrip(".")
    if len(first_sentence) <= max_chars:
        return first_sentence + "."
    return first_sentence[: max_chars - 1].rstrip() + "."


def _extract_assigned_tasks(events: list[EventRecord], context: RunContext) -> list[AgentTaskAssignedPayload]:
    output: list[AgentTaskAssignedPayload] = []
    for event in events:
        if event.type != AGENT_TASK_ASSIGNED_EVENT:
            continue
        try:
            payload = AgentTaskAssignedPayload.from_payload(event.payload)
        except ValidationError as exc:
            _logger.warning("跳过非法 agent task 事件: event_id=%s error=%s", event.event_id, exc)
            continue
        if payload.target_agent_id != context.agent_id:
            continue
        output.append(payload)
    return output


def _extract_child_result_summaries(
    events: list[EventRecord],
    context: RunContext,
) -> list[AgentResultSummaryPayload]:
    output: list[AgentResultSummaryPayload] = []
    for event in events:
        if event.type != AGENT_RESULT_SUMMARY_EVENT:
            continue
        try:
            payload = AgentResultSummaryPayload.from_payload(event.payload)
        except ValidationError as exc:
            _logger.warning("跳过非法 agent result summary 事件: event_id=%s error=%s", event.event_id, exc)
            continue
        if payload.target_agent_id != context.agent_id:
            continue
        output.append(payload)
    return output


def _format_assigned_task_lines(tasks: list[AgentTaskAssignedPayload]) -> list[str]:
    lines: list[str] = []
    for task in tasks:
        extras = _format_optional_payload_parts(
            [
                ("constraints", task.constraints),
                ("artifact_refs", task.artifact_refs),
            ]
        )
        suffix = f" [{'; '.join(extras)}]" if extras else ""
        lines.append(
            f"- task_id={task.task_id} from={task.source_agent_id} instruction={task.instruction}{suffix}"
        )
    return lines


def _format_child_result_summary_lines(results: list[AgentResultSummaryPayload]) -> list[str]:
    lines: list[str] = []
    for result in results:
        extras = _format_optional_payload_parts(
            [
                ("next_steps", result.next_steps),
                ("artifact_refs", result.artifact_refs),
            ]
        )
        suffix = f" [{'; '.join(extras)}]" if extras else ""
        lines.append(
            f"- task_id={result.task_id} agent={result.source_agent_id} status={result.status} "
            f"summary={result.summary}{suffix}"
        )
    return lines


def _format_optional_payload_parts(parts: list[tuple[str, list[str]]]) -> list[str]:
    output: list[str] = []
    for label, values in parts:
        if not values:
            continue
        output.append(f"{label}: {', '.join(values)}")
    return output


def _is_other_agent_related_event(event: EventRecord, context: RunContext) -> bool:
    if event.agent_id == context.agent_id:
        return True
    if event.run_id == context.run_id:
        return True
    return event.parent_run_id == context.run_id
