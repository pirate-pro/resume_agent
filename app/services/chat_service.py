"""Use-case orchestration for chat APIs."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import ValidationError
from app.domain.models import AgentRunInput, AgentRunOutput, EventRecord, MemoryItem, RunContext, SessionFile, SessionMeta
from app.domain.protocols import SessionRepository
from app.infra.locks.session_lock_manager import SessionLockManager
from app.runtime.agent_capability import AgentCapabilityRegistry
from app.runtime.agent_runtime import AgentRuntime
from app.runtime.event_channel import EventChannel
from app.runtime.memory_manager import MemoryManager
from app.runtime.session_manager import SessionManager
from app.schemas.chat import (
    ActiveFilesRequest,
    ChatRequest,
    ChatResponse,
    MemoryView,
    SessionFileView,
    SessionFilesResponse,
    ToolCallView,
)

__all__ = ["ChatService"]
_logger = logging.getLogger(__name__)
_SUPPORTED_FILE_EXTENSIONS = {".pdf", ".md", ".markdown", ".json", ".txt", ".png", ".jpg", ".jpeg", ".webp"}
_MAX_UPLOAD_SIZE_BYTES = 12 * 1024 * 1024


class ChatService:
    """Coordinate HTTP DTOs and runtime execution."""

    def __init__(
        self,
        runtime: AgentRuntime,
        session_manager: SessionManager,
        session_repository: SessionRepository,
        memory_manager: MemoryManager,
        capability_registry: AgentCapabilityRegistry,
        session_lock_manager: SessionLockManager,
    ) -> None:
        self._runtime = runtime
        self._session_manager = session_manager
        self._session_repository = session_repository
        self._memory_manager = memory_manager
        self._capability_registry = capability_registry
        self._session_lock_manager = session_lock_manager

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not isinstance(request, ChatRequest):
            raise ValidationError("request must be ChatRequest.")

        session, run_input = self._prepare_run_input(request)
        _logger.debug("开始编排 chat 用例: input_session_id=%s resolved_session_id=%s", request.session_id, session.session_id)

        lock = self._session_lock_manager.get_lock(session.session_id)
        _logger.debug("准备获取会话锁: session_id=%s", session.session_id)
        # 同一个 session 的 run 串行执行，避免事件日志和文件写入交错。
        async with lock:
            _logger.debug("会话锁已获取: session_id=%s", session.session_id)
            run_output = await asyncio.to_thread(self._runtime.run, run_input)

        chat_response = self._to_chat_response(run_output)
        _logger.info(
            "chat 用例执行完成: session_id=%s answer_len=%s tool_calls=%s",
            chat_response.session_id,
            len(chat_response.answer),
            len(chat_response.tool_calls),
        )
        return chat_response

    async def chat_stream(self, request: ChatRequest) -> AsyncIterator[dict[str, Any]]:
        """以流式方式执行对话：runtime 直接推送 run_event/answer_delta。"""
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

        async def _run_with_lock() -> AgentRunOutput:
            try:
                async with lock:
                    return await self._runtime.run_stream(run_input, channel)
            finally:
                await channel.close()

        run_task = asyncio.create_task(_run_with_lock())
        yield {"event": "session", "data": {"session_id": session_id}}

        try:
            async for item in channel.listen():
                yield item
            run_output = await run_task
            chat_response = self._to_chat_response(run_output)
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

    def list_sessions(self) -> list[SessionMeta]:
        sessions = self._session_repository.list_sessions()
        _logger.debug("读取会话列表: count=%s", len(sessions))
        return sessions

    def create_session(self, session_id: str | None = None) -> SessionMeta:
        session = self._session_manager.get_or_create_session(session_id)
        _logger.info("创建会话请求完成: session_id=%s", session.session_id)
        return session

    def list_session_events(self, session_id: str) -> list[EventRecord]:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        events = self._session_repository.list_events(normalized)
        _logger.debug("读取会话事件: session_id=%s event_count=%s", normalized, len(events))
        return events

    def list_memories(
        self,
        query: str | None,
        limit: int,
        request_agent_id: str,
        target_agent_id: str | None = None,
    ) -> list[MemoryItem]:
        if limit <= 0:
            raise ValidationError("limit must be positive.")
        if not isinstance(request_agent_id, str) or not request_agent_id.strip():
            raise ValidationError("request_agent_id must be a non-empty string.")
        normalized_request_agent_id = request_agent_id.strip()
        normalized_target_agent_id = (
            target_agent_id.strip()
            if isinstance(target_agent_id, str) and target_agent_id.strip()
            else None
        )
        if query is None or not query.strip():
            memories = self._memory_manager.list_memories_for_agent(
                limit=limit,
                request_agent_id=normalized_request_agent_id,
                target_agent_id=normalized_target_agent_id,
            )
            _logger.debug(
                "读取记忆列表: request_agent=%s target_agent=%s limit=%s result_count=%s",
                normalized_request_agent_id,
                normalized_target_agent_id or normalized_request_agent_id,
                limit,
                len(memories),
            )
            return memories
        normalized = query.strip()
        memories = self._memory_manager.search_for_agent(
            query=normalized,
            limit=limit,
            request_agent_id=normalized_request_agent_id,
            target_agent_id=normalized_target_agent_id,
        )
        _logger.debug(
            "检索记忆: request_agent=%s target_agent=%s query=%s limit=%s result_count=%s",
            normalized_request_agent_id,
            normalized_target_agent_id or normalized_request_agent_id,
            normalized,
            limit,
            len(memories),
        )
        return memories

    async def upload_session_file(
        self,
        session_id: str,
        filename: str,
        content_bytes: bytes,
        *,
        auto_activate: bool = True,
    ) -> SessionFileView:
        if not isinstance(filename, str):
            raise ValidationError("filename must be string.")
        if not isinstance(content_bytes, bytes):
            raise ValidationError("content_bytes must be bytes.")
        session = self._session_manager.get_or_create_session(session_id)
        lock = self._session_lock_manager.get_lock(session.session_id)
        async with lock:
            filename = _sanitize_filename(filename)
            extension = _normalized_extension(filename)
            if extension not in _SUPPORTED_FILE_EXTENSIONS:
                supported = ", ".join(sorted(_SUPPORTED_FILE_EXTENSIONS))
                raise ValidationError(f"Unsupported file type '{extension}'. supported={supported}")

            size_bytes = len(content_bytes)
            if size_bytes <= 0:
                raise ValidationError("Uploaded file is empty.")
            if size_bytes > _MAX_UPLOAD_SIZE_BYTES:
                raise ValidationError(f"Uploaded file too large, max={_MAX_UPLOAD_SIZE_BYTES} bytes.")

            file_id = f"file_{uuid4().hex[:12]}"
            workspace = self._session_repository.get_workspace_path(session.session_id)
            session_root = self._session_repository.get_session_root_path(session.session_id)
            uploads_dir = workspace / "uploads"
            uploads_dir.mkdir(parents=True, exist_ok=True)

            storage_path = uploads_dir / f"{file_id}_{filename}"
            storage_path.write_bytes(content_bytes)

            media_type = _infer_media_type(extension)
            record = SessionFile(
                file_id=file_id,
                session_id=session.session_id,
                filename=filename,
                media_type=media_type,
                size_bytes=size_bytes,
                status="uploaded",
                uploaded_at=_utc_now(),
                storage_relpath=str(storage_path.resolve().relative_to(session_root.resolve())),
                text_relpath=None,
                error=None,
                parsed_char_count=None,
                parsed_token_estimate=None,
                parsed_at=None,
            )
            self._session_repository.add_or_update_session_file(record)
            if auto_activate:
                current = self._session_repository.get_active_file_ids(session.session_id)
                self._session_repository.set_active_file_ids(session.session_id, [*current, file_id])

            _logger.info(
                "上传会话文件完成: session_id=%s file_id=%s filename=%s status=%s size=%s",
                session.session_id,
                file_id,
                filename,
                record.status,
                size_bytes,
            )
            return self._to_file_view(record)

    def list_session_files(self, session_id: str) -> SessionFilesResponse:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        files = self._session_repository.list_session_files(normalized)
        active_file_ids = self._session_repository.get_active_file_ids(normalized)
        return SessionFilesResponse(
            session_id=normalized,
            active_file_ids=active_file_ids,
            files=[self._to_file_view(item) for item in files],
        )

    def set_active_files(self, session_id: str, request: ActiveFilesRequest) -> SessionFilesResponse:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        if not isinstance(request, ActiveFilesRequest):
            raise ValidationError("request must be ActiveFilesRequest.")
        normalized = session_id.strip()
        active = self._session_repository.set_active_file_ids(normalized, request.file_ids)
        files = self._session_repository.list_session_files(normalized)
        return SessionFilesResponse(
            session_id=normalized,
            active_file_ids=active,
            files=[self._to_file_view(item) for item in files],
        )

    async def delete_session(self, session_id: str) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValidationError("session_id must be a non-empty string.")
        normalized = session_id.strip()
        lock = self._session_lock_manager.get_lock(normalized)
        async with lock:
            await asyncio.to_thread(self._session_repository.delete_session, normalized)

    def _prepare_run_input(self, request: ChatRequest) -> tuple[SessionMeta, AgentRunInput]:
        session = self._session_manager.get_or_create_session(request.session_id)
        if request.active_file_ids is not None:
            self._session_repository.set_active_file_ids(session.session_id, request.active_file_ids)
        skill_names = request.skill_names or ["base", "memory", "memory-editor", "tools", "file-reader"]
        normalized_agent_id = request.entry_agent_id.strip()
        # 入口 agent 必须先在能力矩阵中声明，避免隐式 agent 绕过权限模型。
        self._capability_registry.require(normalized_agent_id)
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

    def _to_chat_response(self, run_output: AgentRunOutput) -> ChatResponse:
        return ChatResponse(
            session_id=run_output.session_id,
            answer=run_output.answer,
            tool_calls=[ToolCallView(name=call.name, arguments=call.arguments) for call in run_output.tool_calls],
            memory_hits=[
                MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags)
                for item in run_output.memory_hits
            ],
        )

    def _to_file_view(self, item: SessionFile) -> SessionFileView:
        return SessionFileView(
            file_id=item.file_id,
            filename=item.filename,
            media_type=item.media_type,
            size_bytes=item.size_bytes,
            status=item.status,
            uploaded_at=item.uploaded_at,
            error=item.error,
            parsed_char_count=item.parsed_char_count,
            parsed_token_estimate=item.parsed_token_estimate,
            parsed_at=item.parsed_at,
        )


def _sanitize_filename(raw: str) -> str:
    candidate = Path(raw).name.strip()
    if not candidate:
        raise ValidationError("filename cannot be empty.")
    return candidate.replace("/", "_").replace("\\", "_")


def _normalized_extension(filename: str) -> str:
    suffix = Path(filename).suffix.lower().strip()
    if not suffix:
        raise ValidationError("filename must have extension.")
    return suffix


def _infer_media_type(extension: str) -> str:
    mapping = {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".markdown": "text/markdown",
        ".json": "application/json",
        ".txt": "text/plain",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }
    return mapping.get(extension, "application/octet-stream")


def _utc_now() -> datetime:
    return datetime.now(UTC)
