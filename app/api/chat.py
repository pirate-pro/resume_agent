"""Chat-related HTTP endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_chat_service
from app.core.errors import (
    AppError,
    ModelClientError,
    SessionNotFoundError,
    StorageError,
    ToolExecutionError,
    ValidationError,
)
from app.schemas.chat import ChatRequest, ChatResponse, EventView, MemoryView
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
                type=item.type,
                payload=item.payload,
                created_at=item.created_at,
            )
            for item in events
        ]
    except AppError as exc:
        _logger.exception("查询会话事件失败: session_id=%s error=%s", session_id, exc)
        raise _map_app_error(exc) from exc


@router.get("/memories", response_model=list[MemoryView])
async def get_memories(
    q: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    service: ChatService = Depends(get_chat_service),
) -> list[MemoryView]:
    _logger.info("查询记忆: query=%s limit=%s", q, limit)
    try:
        items = service.list_memories(q, limit)
        _logger.info("记忆查询完成: query=%s result_count=%s", q, len(items))
        return [MemoryView(memory_id=item.memory_id, content=item.content, tags=item.tags) for item in items]
    except AppError as exc:
        _logger.exception("查询记忆失败: query=%s limit=%s error=%s", q, limit, exc)
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
