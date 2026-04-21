"""Use-case orchestration for chat APIs."""

from __future__ import annotations

import asyncio
import logging

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, EventRecord, MemoryItem
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.schemas.chat import ChatRequest, ChatResponse, MemoryView, ToolCallView

__all__ = ["ChatService"]
_logger = logging.getLogger(__name__)


class ChatService:
    """Coordinate HTTP DTOs and runtime execution."""

    def __init__(
        self,
        runtime: AgentRuntime,
        session_manager: SessionManager,
        session_repository: SessionRepository,
        memory_manager: MemoryManager,
        session_lock_manager: SessionLockManager,
    ) -> None:
        self._runtime = runtime
        self._session_manager = session_manager
        self._session_repository = session_repository
        self._memory_manager = memory_manager
        self._session_lock_manager = session_lock_manager

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not isinstance(request, ChatRequest):
            raise ValidationError("request must be ChatRequest.")

        _logger.debug("开始编排 chat 用例: input_session_id=%s", request.session_id)
        session = self._session_manager.get_or_create_session(request.session_id)
        skill_names = request.skill_names or ["base", "memory", "tools"]
        run_input = AgentRunInput(
            session_id=session.session_id,
            user_message=request.message,
            skill_names=skill_names,
            max_tool_rounds=request.max_tool_rounds,
        )

        lock = self._session_lock_manager.get_lock(session.session_id)
        _logger.debug("准备获取会话锁: session_id=%s", session.session_id)
        # 同一个 session 的 run 串行执行，避免事件日志和文件写入交错。
        async with lock:
            _logger.debug("会话锁已获取: session_id=%s", session.session_id)
            run_output = await asyncio.to_thread(self._runtime.run, run_input)

        _logger.info(
            "chat 用例执行完成: session_id=%s answer_len=%s tool_calls=%s",
            run_output.session_id,
            len(run_output.answer),
            len(run_output.tool_calls),
        )
        return ChatResponse(
            session_id=run_output.session_id,
            answer=run_output.answer,
            tool_calls=[ToolCallView(name=call.name, arguments=call.arguments) for call in run_output.tool_calls],
            memory_hits=[
                MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags)
                for item in run_output.memory_hits
            ],
        )

    def list_session_events(self, session_id: str) -> list[EventRecord]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        events = self._session_repository.list_events(normalized)
        _logger.debug("读取会话事件: session_id=%s event_count=%s", normalized, len(events))
        return events

    def list_memories(self, query: str | None, limit: int) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        if query is None or not query.strip():
            memories = self._memory_manager.list_memories(limit)
            _logger.debug("读取记忆列表: limit=%s result_count=%s", limit, len(memories))
            return memories
        normalized = query.strip()
        memories = self._memory_manager.search(normalized, limit)
        _logger.debug("检索记忆: query=%s limit=%s result_count=%s", normalized, limit, len(memories))
        return memories
