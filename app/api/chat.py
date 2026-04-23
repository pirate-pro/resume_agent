"""Chat-related HTTP endpoints."""

from __future__ import annotations

import json
import logging
from base64 import b64decode
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service, get_skill_repository
from app.core.errors import (
    AppError,
    ModelClientError,
    SessionNotFoundError,
    StorageError,
    ToolExecutionError,
    ValidationError,
)
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.schemas.chat import (
    ActiveFilesRequest,
    ChatRequest,
    ChatResponse,
    CreateSessionResponse,
    EventView,
    FileUploadRequest,
    MemoryView,
    SessionView,
    SessionDeleteResponse,
    SessionFileView,
    SessionFilesResponse,
    SkillView,
)
from app.services.chat_service import ChatService

__all__ = ["router"]

router = APIRouter(prefix="/api", tags=["chat"])
_logger = logging.getLogger(__name__)


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    _logger.info(
        "收到聊天请求: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
        request.session_id,
        len(request.message),
        len(request.skill_names),
        request.max_tool_rounds,
    )
    try:
        response = await service.chat(request)
        _logger.info(
            "聊天请求处理完成: session_id=%s answer_len=%s tool_calls=%s memory_hits=%s",
            response.session_id,
            len(response.answer),
            len(response.tool_calls),
            len(response.memory_hits),
        )
        return response
    except AppError as exc:
        _logger.exception("聊天请求失败: %s", exc)
        raise _map_app_error(exc) from exc


@router.get("/sessions", response_model=list[SessionView])
async def get_sessions(
    service: ChatService = Depends(get_chat_service),
) -> list[SessionView]:
    _logger.info("查询会话列表")
    try:
        sessions = service.list_sessions()
        return [
            SessionView(
                id=item.session_id,
                title=item.title,
                preview=None,
                messages=[],
                updated_at=item.updated_at,
            )
            for item in sessions
        ]
    except AppError as exc:
        _logger.exception("查询会话列表失败: %s", exc)
        raise _map_app_error(exc) from exc


@router.post("/sessions", response_model=CreateSessionResponse)
async def post_session(
    service: ChatService = Depends(get_chat_service),
) -> CreateSessionResponse:
    _logger.info("创建会话请求")
    try:
        session = service.create_session()
        return CreateSessionResponse(session_id=session.session_id)
    except AppError as exc:
        _logger.exception("创建会话失败: %s", exc)
        raise _map_app_error(exc) from exc


@router.get("/skills", response_model=list[SkillView])
async def get_skills(
    skill_repository: MarkdownSkillRepository = Depends(get_skill_repository),
) -> list[SkillView]:
    _logger.info("查询技能列表")
    try:
        # 复用 Skill 仓库索引，返回前端需要的 id/name/description 结构。
        skill_index = skill_repository._build_skill_index()
        return [
            SkillView(
                id=item.name,
                name=item.name,
                description=item.description,
                enabled=True,
            )
            for item in skill_index.values()
        ]
    except AppError as exc:
        _logger.exception("查询技能列表失败: %s", exc)
        raise _map_app_error(exc) from exc


@router.post("/chat/stream")
async def post_chat_stream(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    _logger.info(
        "收到流式聊天请求: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
        request.session_id,
        len(request.message),
        len(request.skill_names),
        request.max_tool_rounds,
    )

    async def _event_generator() -> AsyncIterator[str]:
        try:
            async for item in service.chat_stream(request):
                event_name = str(item.get("event", "message"))
                event_data = item.get("data", {})
                yield _format_sse(event_name, event_data)
        except Exception as exc:
            _logger.exception("流式聊天处理失败: %s", exc)
            yield _format_sse("error", {"detail": str(exc)})

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sessions/{session_id}/files/upload", response_model=SessionFileView)
async def post_session_file_upload(
    session_id: str,
    request: FileUploadRequest,
    service: ChatService = Depends(get_chat_service),
) -> SessionFileView:
    _logger.info(
        "收到会话文件上传请求: session_id=%s filename=%s auto_activate=%s",
        session_id,
        request.filename,
        request.auto_activate,
    )
    try:
        try:
            file_bytes = b64decode(request.content_base64, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValidationError(f"Invalid base64 content: {exc}") from exc
        return await service.upload_session_file(
            session_id=session_id,
            filename=request.filename,
            content_bytes=file_bytes,
            auto_activate=request.auto_activate,
        )
    except AppError as exc:
        _logger.exception("会话文件上传失败: session_id=%s error=%s", session_id, exc)
        raise _map_app_error(exc) from exc


@router.get("/sessions/{session_id}/files", response_model=SessionFilesResponse)
async def get_session_files(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
) -> SessionFilesResponse:
    _logger.info("查询会话文件列表: session_id=%s", session_id)
    try:
        return service.list_session_files(session_id)
    except AppError as exc:
        _logger.exception("查询会话文件列表失败: session_id=%s error=%s", session_id, exc)
        raise _map_app_error(exc) from exc


@router.post("/sessions/{session_id}/active-files", response_model=SessionFilesResponse)
async def post_session_active_files(
    session_id: str,
    request: ActiveFilesRequest,
    service: ChatService = Depends(get_chat_service),
) -> SessionFilesResponse:
    _logger.info("更新会话 active files: session_id=%s file_count=%s", session_id, len(request.file_ids))
    try:
        return service.set_active_files(session_id, request)
    except AppError as exc:
        _logger.exception("更新会话 active files 失败: session_id=%s error=%s", session_id, exc)
        raise _map_app_error(exc) from exc


@router.get("/sessions/{session_id}/events", response_model=list[EventView])
async def get_session_events(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
) -> list[EventView]:
    _logger.info("查询会话事件: session_id=%s", session_id)
    try:
        events = service.list_session_events(session_id)
        _logger.info("会话事件查询完成: session_id=%s event_count=%s", session_id, len(events))
        return [
            EventView(
                event_id=item.event_id,
                session_id=item.session_id,
                agent_id=item.agent_id,
                run_id=item.run_id,
                parent_run_id=item.parent_run_id,
                event_version=item.event_version,
                type=item.type,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in events
        ]
    except AppError as exc:
        _logger.exception("查询会话事件失败: session_id=%s error=%s", session_id, exc)
        raise _map_app_error(exc) from exc


@router.delete("/sessions/{session_id}", response_model=SessionDeleteResponse)
async def delete_session(
    session_id: str,
    service: ChatService = Depends(get_chat_service),
) -> SessionDeleteResponse:
    normalized = session_id.strip()
    _logger.info("删除会话请求: session_id=%s", normalized)
    try:
        await service.delete_session(normalized)
        return SessionDeleteResponse(session_id=normalized, deleted=True)
    except AppError as exc:
        _logger.exception("删除会话失败: session_id=%s error=%s", normalized, exc)
        raise _map_app_error(exc) from exc


@router.get("/memories", response_model=list[MemoryView])
async def get_memories(
    q: str | None = Query(default=None),
    agent_id: str = Query(default="agent_main"),
    target_agent_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    service: ChatService = Depends(get_chat_service),
) -> list[MemoryView]:
    _logger.info(
        "查询记忆: request_agent=%s target_agent=%s query=%s limit=%s",
        agent_id,
        target_agent_id,
        q,
        limit,
    )
    try:
        items = service.list_memories(
            q,
            limit,
            request_agent_id=agent_id,
            target_agent_id=target_agent_id,
        )
        _logger.info(
            "记忆查询完成: request_agent=%s target_agent=%s query=%s result_count=%s",
            agent_id,
            target_agent_id,
            q,
            len(items),
        )
        return [MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags) for item in items]
    except AppError as exc:
        _logger.exception(
            "查询记忆失败: request_agent=%s target_agent=%s query=%s limit=%s error=%s",
            agent_id,
            target_agent_id,
            q,
            limit,
            exc,
        )
        raise _map_app_error(exc) from exc


def _format_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _map_app_error(error: AppError) -> HTTPException:
    if isinstance(error, SessionNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error))
    if isinstance(error, ValidationError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))
    if isinstance(error, (ToolExecutionError, StorageError, ModelClientError)):
        return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(error))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal server error")
