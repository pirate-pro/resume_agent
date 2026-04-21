"""Compose system prompt, messages, memory, and tool context."""

from __future__ import annotations

import logging

from app.core.errors import ValidationError
from app.domain.models import ContextBundle, EventRecord, MemoryItem
from app.domain.protocols import SessionRepository, SkillRepository, ToolExecutor
from app.runtime.memory_manager import MemoryManager

__all__ = ["ContextAssembler"]
_logger = logging.getLogger(__name__)


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

    def assemble(self, session_id: str, user_message: str, skill_names: list[str]) -> ContextBundle:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValidationError("user_message must be a non-empty string.")
        if not isinstance(skill_names, list):
            raise ValidationError("skill_names must be a list.")

        normalized_session_id = session_id.strip()
        normalized_message = user_message.strip()

        skills = self._skill_repository.load_skills(skill_names) if skill_names else {}
        memory_hits = self._safe_memory_search(normalized_message, limit=5)
        recent_events = self._session_repository.list_recent_events(normalized_session_id, limit=12)
        messages = self._build_messages_from_events(recent_events)
        # 用户当前这条输入必须进入模型消息，否则会出现“模型只看历史不看当前”的问题。
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != normalized_message:
            messages.append({"role": "user", "content": normalized_message})

        system_prompt = self._build_system_prompt(skills, memory_hits)
        tool_definitions = self._tool_executor.list_definitions()
        _logger.debug(
            "上下文组装: session_id=%s skills=%s memory_hits=%s recent_events=%s output_messages=%s",
            normalized_session_id,
            len(skills),
            len(memory_hits),
            len(recent_events),
            len(messages),
        )
        return ContextBundle(
            system_prompt=system_prompt,
            messages=messages,
            memory_hits=memory_hits,
            tool_definitions=tool_definitions,
        )

    def _safe_memory_search(self, query: str, limit: int) -> list[MemoryItem]:
        try:
            return self._memory_manager.search(query=query, limit=limit)
        except ValidationError as exc:
            _logger.warning("记忆检索参数不合法，跳过检索: query=%s limit=%s error=%s", query, limit, exc)
            return []

    def _build_system_prompt(self, skills: dict[str, str], memory_hits: list[MemoryItem]) -> str:
        sections: list[str] = [
            "You are a pragmatic assistant. Use tools when needed and never fabricate tool results.",
            "If information is unknown, say you do not know.",
        ]
        if skills:
            sections.append("Skills:\n" + "\n\n".join(f"[{name}]\n{text}" for name, text in skills.items()))
        if memory_hits:
            memory_lines = [f"- ({item.memory_id}) {item.content} [tags: {', '.join(item.tags)}]" for item in memory_hits]
            sections.append("Relevant memories:\n" + "\n".join(memory_lines))
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
