"""Use-case orchestration for chat APIs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from collections.abc import Coroutine
from datetime import datetime
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.core.time import app_now, to_app_iso
from app.domain.models import AgentRunInput, AgentRunOutput, RunContext, SessionMeta
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.event_channel import EventChannel
from app.runtime.session_manager import SessionManager
from app.services.answer_normalizer import AnswerNormalizer
from app.services.chat_response_builder import ChatResponseBuilder
from app.services.session_title_service import DEFAULT_SESSION_TITLES, SessionTitleService
from app.schemas.chat import ChatRequest, ChatResponse

__all__ = ["ChatService"]
_logger = logging.getLogger(__name__)


class ChatService:
    """Coordinate HTTP DTOs and runtime execution."""

    def __init__(
        self,
        runtime: AgentRuntime,
        session_manager: SessionManager,
        session_repository: SessionRepository,
        capability_registry: AgentCapabilityRegistry,
        session_lock_manager: SessionLockManager,
        session_title_service: SessionTitleService,
        answer_normalizer: AnswerNormalizer | None = None,
        stream_heartbeat_interval_seconds: float = 15.0,
        stream_run_timeout_seconds: float = 300.0,
        session_title_timeout_seconds: float = 40.0,
    ) -> None:
        self._runtime = runtime
        self._session_manager = session_manager
        self._session_repository = session_repository
        self._capability_registry = capability_registry
        self._session_lock_manager = session_lock_manager
        self._session_title_service = session_title_service
        self._chat_response_builder = ChatResponseBuilder(answer_normalizer)
        if stream_heartbeat_interval_seconds <= 0:
            raise ValidationError("stream_heartbeat_interval_seconds must be positive.")
        if stream_run_timeout_seconds <= 0:
            raise ValidationError("stream_run_timeout_seconds must be positive.")
        if session_title_timeout_seconds <= 0:
            raise ValidationError("session_title_timeout_seconds must be positive.")
        self._stream_heartbeat_interval_seconds = stream_heartbeat_interval_seconds
        self._stream_run_timeout_seconds = stream_run_timeout_seconds
        self._session_title_timeout_seconds = session_title_timeout_seconds
        self._background_tasks: set[asyncio.Task[None]] = set()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not isinstance(request, ChatRequest):
            raise ValidationError("request must be ChatRequest.")

        session, run_input = self._prepare_run_input(request)
        _logger.debug("开始编排 chat 用例: input_session_id=%s resolved_session_id=%s", request.session_id, session.session_id)

        lock = self._session_lock_manager.get_lock(session.session_id)
        _logger.debug("准备获取会话锁: session_id=%s", session.session_id)
        should_generate_title = False
        # 同一个 session 的 run 串行执行，避免事件日志和文件写入交错。
        async with lock:
            _logger.debug("会话锁已获取: session_id=%s", session.session_id)
            should_generate_title = await asyncio.to_thread(
                self._should_generate_session_title,
                session.session_id,
            )
            run_output = await asyncio.to_thread(self._runtime.run, run_input)

        title_pending = False
        if should_generate_title:
            title_pending = self._schedule_session_title_generation(
                session.session_id,
                request.message,
                run_output.answer,
            )

        chat_response = self._chat_response_builder.build(run_output, title_pending=title_pending)
        _logger.info(
            "chat 用例执行完成: session_id=%s answer_len=%s tool_calls=%s",
            chat_response.session_id,
            len(chat_response.answer),
            len(chat_response.tool_calls),
        )
        return chat_response

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        """以流式方式执行对话：runtime 直接推送 run_event/answer_meta/answer_delta。"""
        if not isinstance(request, ChatRequest):
            raise ValidationError("request must be ChatRequest.")

        session, run_input = self._prepare_run_input(request)
        session_id = session.session_id
        _logger.info(
            "chat_stream 开始: session_id=%s message_len=%s skill_count=%s",
            session_id,
            len(request.message),
            len(run_input.skill_names),
        )

        lock = self._session_lock_manager.get_lock(session_id)
        channel = EventChannel(maxsize=512)

        async def _run_with_lock() -> tuple[AgentRunOutput, bool]:
            try:
                async with lock:
                    should_generate_title = await asyncio.to_thread(
                        self._should_generate_session_title,
                        session_id,
                    )
                    run_output = await asyncio.wait_for(
                        self._runtime.run_stream(run_input, channel),
                        timeout=self._stream_run_timeout_seconds,
                    )
                    return run_output, should_generate_title
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"chat_stream run timed out after {self._stream_run_timeout_seconds:.1f}s"
                ) from exc
            finally:
                await channel.close()

        run_task = asyncio.create_task(_run_with_lock())
        yield {"event": "session", "data": {"session_id": session_id}}

        try:
            while True:
                try:
                    item = await channel.receive(timeout_seconds=self._stream_heartbeat_interval_seconds)
                except asyncio.TimeoutError:
                    # 长时间无事件时推送心跳，避免前端误判为断流。
                    yield {
                        "event": "heartbeat",
                        "data": {
                            "session_id": session_id,
                            "idle_seconds": self._stream_heartbeat_interval_seconds,
                            "created_at": to_app_iso(_utc_now()),
                        },
                    }
                    if run_task.done():
                        _logger.warning(
                            "run_task 已完成但 channel 未收到关闭信号，强制结束监听: session_id=%s",
                            session_id,
                        )
                        break
                    continue

                if item is None:
                    break
                yield item

            run_output, should_generate_title = await run_task
            title_pending = False
            if should_generate_title:
                title_pending = self._schedule_session_title_generation(
                    session_id,
                    request.message,
                    run_output.answer,
                )
            chat_response = self._chat_response_builder.build(run_output, title_pending=title_pending)
            yield {"event": "done", "data": chat_response.model_dump(mode="json")}
            _logger.info(
                "chat_stream 完成: session_id=%s answer_len=%s tool_calls=%s",
                chat_response.session_id,
                len(chat_response.answer),
                len(chat_response.tool_calls),
            )
        except Exception as exc:
            _logger.exception("chat_stream 失败: session_id=%s error=%s", session_id, exc)
            if not run_task.done():
                run_task.cancel()
                try:
                    await run_task
                except asyncio.CancelledError:
                    pass
            await channel.close()
            yield {"event": "error", "data": {"detail": str(exc)}}

    async def wait_for_background_tasks(self) -> None:
        if not self._background_tasks:
            return
        await asyncio.gather(*list(self._background_tasks), return_exceptions=True)

    def _prepare_run_input(self, request: ChatRequest) -> tuple[SessionMeta, AgentRunInput]:
        session = self._session_manager.get_or_create_session(request.session_id)
        if request.active_artifact_ids is not None:
            self._session_repository.set_active_artifact_ids(session.session_id, request.active_artifact_ids)
        normalized_agent_id = request.entry_agent_id.strip()
        # 入口 agent 必须先在能力矩阵中声明，避免隐式 agent 绕过权限模型。
        capability = self._capability_registry.require(normalized_agent_id)
        skill_names = capability.resolve_skill_names(request.skill_names or None)
        run_context = RunContext(
            session_id=session.session_id,
            run_id=f"run_{uuid4().hex[:12]}",
            agent_id=normalized_agent_id,
            turn_id=f"turn_{uuid4().hex[:12]}",
            entry_agent_id=normalized_agent_id,
            parent_run_id=None,
            trace_flags={"verbose": request.trace_level == "verbose"},
        )
        run_input = AgentRunInput(
            session_id=session.session_id,
            user_message=request.message,
            skill_names=skill_names,
            max_tool_rounds=request.max_tool_rounds,
            context=run_context,
        )
        return session, run_input

    def _should_generate_session_title(self, session_id: str) -> bool:
        meta = self._session_repository.get_session(session_id)
        if meta is None:
            return False
        if meta.title not in DEFAULT_SESSION_TITLES:
            return False
        messages = self._session_repository.list_session_messages(session_id)
        assistant_count = sum(1 for item in messages if str(item.get("role", "")) == "assistant")
        return assistant_count == 0

    def _generate_and_persist_session_title(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
    ) -> None:
        if not str(assistant_answer).strip():
            return
        latest = self._session_repository.get_session(session_id)
        if latest is None or latest.title not in DEFAULT_SESSION_TITLES:
            return
        title = self._session_title_service.generate_title(
            user_message=user_message,
            assistant_answer=assistant_answer,
        )
        self._session_repository.update_session_title(session_id, title)
        _logger.info("首轮对话标题生成完成: session_id=%s title=%s", session_id, title)

    def _schedule_session_title_generation(
        self,
        session_id: str,
        user_message: str,
        assistant_answer: str,
    ) -> bool:
        if not str(assistant_answer).strip():
            return False
        self._spawn_background_task(
            self._generate_and_persist_session_title_async(
                session_id=session_id,
                user_message=user_message,
                assistant_answer=assistant_answer,
            ),
            name=f"session-title:{session_id}",
        )
        return True

    def _spawn_background_task(
        self,
        coroutine: Coroutine[Any, Any, None],
        *,
        name: str,
    ) -> None:
        task = asyncio.create_task(coroutine, name=name)
        self._background_tasks.add(task)

        def _on_done(completed: asyncio.Task[None]) -> None:
            self._background_tasks.discard(completed)
            try:
                exc = completed.exception()
            except asyncio.CancelledError:
                return
            if exc is not None:
                _logger.error("后台任务执行失败: task=%s error=%s", name, exc, exc_info=exc)

        task.add_done_callback(_on_done)

    async def _generate_and_persist_session_title_async(
        self,
        *,
        session_id: str,
        user_message: str,
        assistant_answer: str,
    ) -> None:
        lock = self._session_lock_manager.get_lock(session_id)
        async with lock:
            latest = await asyncio.to_thread(self._session_repository.get_session, session_id)
            if latest is None or latest.title not in DEFAULT_SESSION_TITLES:
                return
            title = await self._generate_session_title_with_timeout(
                user_message=user_message,
                assistant_answer=assistant_answer,
            )
            latest = await asyncio.to_thread(self._session_repository.get_session, session_id)
            if latest is None or latest.title not in DEFAULT_SESSION_TITLES:
                return
            await asyncio.to_thread(self._session_repository.update_session_title, session_id, title)
            _logger.info("首轮对话标题生成完成: session_id=%s title=%s", session_id, title)

    async def _generate_session_title_with_timeout(
        self,
        *,
        user_message: str,
        assistant_answer: str,
    ) -> str:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self._session_title_service.generate_title,
                    user_message=user_message,
                    assistant_answer=assistant_answer,
                ),
                timeout=self._session_title_timeout_seconds,
            )
        except asyncio.TimeoutError:
            _logger.warning(
                "会话标题生成超时，使用兜底标题: timeout_seconds=%s",
                self._session_title_timeout_seconds,
            )
            return self._session_title_service.fallback_title(user_message=user_message)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("会话标题后台生成失败，使用兜底标题: error=%s", exc)
            return self._session_title_service.fallback_title(user_message=user_message)


def _utc_now() -> datetime:
    return app_now()
