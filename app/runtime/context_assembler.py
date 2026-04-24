"""Compose system prompt, messages, memory, and tool context."""

from __future__ import annotations

import logging

from app.core.errors import ValidationError
from app.domain.models import ContextBundle, EventRecord, MemoryItem, RunContext, SessionFile
from app.domain.protocols import SessionRepository, SkillRepository, ToolExecutor
from app.runtime.memory_manager import MemoryManager

__all__ = ["ContextAssembler"]
_logger = logging.getLogger(__name__)
_ACTIVE_FILE_MAX_COUNT = 12
_OUTPUT_FORMAT_RULES = """Answer output rules:
1. If the user asks for a Markdown document to read/render, return direct Markdown body. Do not wrap the whole document in an outer ```markdown fenced block.
2. Only use ```markdown fenced block when the user explicitly wants Markdown source code.
3. For code answers, always use standard fenced code blocks and include language when you know it.
4. For formulas, use LaTeX: inline $...$ and block $$...$$.
5. If you created or read a file and the user wants to see the content, include the actual final content in the answer instead of only saying it was saved/read.
6. If content is too long to fully display, provide a concise summary first and then clearly state the related file path if applicable."""


class ContextAssembler:
    """Build contextual bundle for one model invocation."""

    def __init__(
        self,
        session_repository: SessionRepository,
        skill_repository: SkillRepository,
        memory_manager: MemoryManager,
        tool_executor: ToolExecutor,
    ) -> None:
        self._session_repository = session_repository
        self._skill_repository = skill_repository
        self._memory_manager = memory_manager
        self._tool_executor = tool_executor

    def assemble(self, context: RunContext, user_message: str, skill_names: list[str]) -> ContextBundle:
        if not isinstance(context, RunContext):
            raise ValidationError("context must be RunContext.")
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValidationError("user_message must be a non-empty string.")
        if not isinstance(skill_names, list):
            raise ValidationError("skill_names must be a list.")

        normalized_session_id = context.session_id
        normalized_message = user_message.strip()

        skills = self._skill_repository.load_skills(skill_names) if skill_names else {}
        memory_hits, memory_summary = self._safe_memory_search(normalized_message, limit=5, context=context)
        active_files = self._load_active_files(normalized_session_id)
        recent_events = self._session_repository.list_recent_events(normalized_session_id, limit=12)
        messages = self._build_messages_from_events(recent_events)
        # 用户当前这条输入必须进入模型消息，否则会出现“模型只看历史不看当前”的问题。
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != normalized_message:
            messages.append({"role": "user", "content": normalized_message})

        system_prompt = self._build_system_prompt(skills, memory_hits, active_files)
        tool_definitions = self._tool_executor.list_definitions()
        _logger.debug(
            "上下文组装: session_id=%s skills=%s memory_hits=%s active_files=%s recent_events=%s output_messages=%s",
            normalized_session_id,
            len(skills),
            len(memory_hits),
            len(active_files),
            len(recent_events),
            len(messages),
        )
        return ContextBundle(
            system_prompt=system_prompt,
            messages=messages,
            memory_hits=memory_hits,
            tool_definitions=tool_definitions,
            memory_summary=memory_summary,
        )

    def _safe_memory_search(
        self,
        query: str,
        limit: int,
        context: RunContext,
    ) -> tuple[list[MemoryItem], dict[str, str | int | bool | list[str]]]:
        try:
            hits, summary = self._memory_manager.search_with_summary(
                query=query,
                limit=limit,
                context=context,
            )
            normalized_summary: dict[str, str | int | bool | list[str]] = {
                "query": str(summary.get("query", "")),
                "agent_id": str(summary.get("agent_id", "")),
                "session_id": str(summary.get("session_id", "")),
                "hit_count": int(summary.get("hit_count", 0)),
                "total_scanned": int(summary.get("total_scanned", 0)),
                "truncated": bool(summary.get("truncated", False)),
                "searched_scopes": [str(item) for item in summary.get("searched_scopes", [])],
                "notes": [str(item) for item in summary.get("notes", [])],
            }
            return hits, normalized_summary
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
            }

    def _build_system_prompt(
        self,
        skills: dict[str, str],
        memory_hits: list[MemoryItem],
        active_files: list[SessionFile],
    ) -> str:
        sections: list[str] = [
            "You are a pragmatic assistant. Use tools when needed and never fabricate tool results.",
            "If information is unknown, say you do not know.",
            _OUTPUT_FORMAT_RULES,
        ]
        if skills:
            sections.append("Skills:\n" + "\n\n".join(f"[{name}]\n{text}" for name, text in skills.items()))
        if memory_hits:
            memory_lines = [f"- ({item.memory_id}) {item.content} [tags: {', '.join(item.tags)}]" for item in memory_hits]
            sections.append("Relevant memories:\n" + "\n".join(memory_lines))
        if active_files:
            file_lines = [
                (
                    f"- file_id={item.file_id} name={item.filename} type={item.media_type} "
                    f"status={item.status} size_bytes={item.size_bytes}"
                )
                for item in active_files
            ]
            sections.append(
                "Active session files (metadata only):\n"
                + "\n".join(file_lines)
                + "\nUse session_list_files/session_read_file/session_search_file when you need file content details."
            )
        return "\n\n".join(sections)

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
