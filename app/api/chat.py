"""Chat-related HTTP endpoints."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, StreamingResponse

from app.api.deps import (
    get_chat_service,
    get_memory_query_service,
    get_session_artifact_service,
    get_session_query_service,
    get_skill_repository,
)
from app.api.presenters import event_view, memory_view, session_item_view, session_message_view, skill_summary_view
from app.api.responses import ok
from app.domain.protocols import SkillRepository
from app.schemas.chat import (
    ActiveArtifactsRequest,
    ArtifactUploadRequest,
    ChatRequest,
    ChatResponse,
    EventView,
    MemoryQueryParams,
    MemoryView,
    SessionDeleteResponse,
    SessionArtifactContentResponse,
    SessionArtifactView,
    SessionArtifactsResponse,
    SessionListItem,
    SessionMessage,
    SessionUpdateRequest,
    SkillSummaryView,
    WorkflowResumeStreamRequest,
    WorkspaceFilePreviewResponse,
)
from app.schemas.common import StandardResponse
from app.services.chat_service import ChatService
from app.services.memory_query_service import MemoryQueryService
from app.services.session_artifact_service import SessionArtifactService
from app.services.session_query_service import SessionQueryService

__all__ = ["router"]

router = APIRouter(prefix="/api", tags=["chat"])
_logger = logging.getLogger(__name__)


@router.get("/sessions", response_model=StandardResponse[list[SessionListItem]])
async def list_sessions(
    service: SessionQueryService = Depends(get_session_query_service),
) -> StandardResponse[list[SessionListItem]]:
    _logger.info("查询会话列表")
    return ok([session_item_view(item) for item in service.list_sessions()])


@router.get("/skills", response_model=StandardResponse[list[SkillSummaryView]])
async def list_skills(
    skill_repository: SkillRepository = Depends(get_skill_repository),
) -> StandardResponse[list[SkillSummaryView]]:
    _logger.info("查询技能列表")
    return ok([skill_summary_view(item) for item in skill_repository.list_skills()])


@router.get("/sessions/{session_id}/messages", response_model=StandardResponse[list[SessionMessage]])
async def get_session_messages(
    session_id: str,
    service: SessionQueryService = Depends(get_session_query_service),
) -> StandardResponse[list[SessionMessage]]:
    _logger.info("查询会话消息: session_id=%s", session_id)
    return ok([session_message_view(item) for item in service.list_session_messages(session_id)])


@router.post("/chat", response_model=StandardResponse[ChatResponse])
async def post_chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> StandardResponse[ChatResponse]:
    _logger.info(
        "收到聊天请求: session_id=%s message_len=%s skill_count=%s max_tool_rounds=%s",
        request.session_id,
        len(request.message),
        len(request.skill_names),
        request.max_tool_rounds,
    )
    response = await service.chat(request)
    _logger.info(
        "聊天请求处理完成: session_id=%s answer_len=%s tool_calls=%s memory_hits=%s",
        response.session_id,
        len(response.answer),
        len(response.tool_calls),
        len(response.memory_hits),
    )
    return ok(response)


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
            # 流式响应已经开始后，全局异常处理器无法再接管，只能发送 SSE error 事件。
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


@router.post("/workflows/{workflow_instance_id}/resume/stream")
async def post_workflow_resume_stream(
    workflow_instance_id: str,
    request: WorkflowResumeStreamRequest,
    service: ChatService = Depends(get_chat_service),
) -> StreamingResponse:
    _logger.info(
        "收到 workflow resume 请求: session_id=%s workflow_instance_id=%s payload_keys=%s",
        request.session_id,
        workflow_instance_id,
        sorted(request.payload.keys()),
    )

    async def _event_generator() -> AsyncIterator[str]:
        try:
            async for item in service.resume_workflow_stream(workflow_instance_id, request):
                event_name = str(item.get("event", "message"))
                event_data = item.get("data", {})
                yield _format_sse(event_name, event_data)
        except Exception as exc:
            _logger.exception("workflow resume 处理失败: %s", exc)
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


@router.post("/sessions/{session_id}/artifacts/upload", response_model=StandardResponse[SessionArtifactView])
async def post_session_artifact_upload(
    session_id: str,
    request: ArtifactUploadRequest,
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> StandardResponse[SessionArtifactView]:
    _logger.info(
        "收到会话 artifact 上传请求: session_id=%s filename=%s auto_activate=%s",
        session_id,
        request.filename,
        request.auto_activate,
    )
    return ok(await service.upload_session_artifact_from_request(session_id, request))


@router.get("/sessions/{session_id}/artifacts", response_model=StandardResponse[SessionArtifactsResponse])
async def get_session_artifacts(
    session_id: str,
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> StandardResponse[SessionArtifactsResponse]:
    _logger.info("查询会话 artifact 列表: session_id=%s", session_id)
    return ok(service.list_session_artifacts(session_id))


@router.get(
    "/sessions/{session_id}/artifacts/{artifact_id}/content",
    response_model=StandardResponse[SessionArtifactContentResponse],
)
async def get_session_artifact_content(
    session_id: str,
    artifact_id: str,
    offset: int = Query(default=0, ge=0),
    max_chars: int = Query(default=12000, ge=200, le=24000),
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> StandardResponse[SessionArtifactContentResponse]:
    _logger.info(
        "读取会话 artifact 正文: session_id=%s artifact_id=%s offset=%s max_chars=%s",
        session_id,
        artifact_id,
        offset,
        max_chars,
    )
    return ok(
        service.read_session_artifact_content(
            session_id,
            artifact_id,
            offset=offset,
            max_chars=max_chars,
        )
    )


@router.get("/sessions/{session_id}/artifacts/{artifact_id}/download")
async def get_session_artifact_download(
    session_id: str,
    artifact_id: str,
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> FileResponse:
    _logger.info("下载会话 artifact: session_id=%s artifact_id=%s", session_id, artifact_id)
    download = service.get_session_artifact_download(session_id, artifact_id)
    return FileResponse(
        download.path,
        media_type=download.media_type,
        filename=download.filename,
    )


@router.post("/sessions/{session_id}/active-artifacts", response_model=StandardResponse[SessionArtifactsResponse])
async def post_session_active_artifacts(
    session_id: str,
    request: ActiveArtifactsRequest,
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> StandardResponse[SessionArtifactsResponse]:
    _logger.info("更新会话 active artifacts: session_id=%s artifact_count=%s", session_id, len(request.artifact_ids))
    return ok(service.set_active_artifacts(session_id, request))


@router.get(
    "/sessions/{session_id}/workspace-files/preview",
    response_model=StandardResponse[WorkspaceFilePreviewResponse],
)
async def get_workspace_file_preview(
    session_id: str,
    path: str = Query(..., min_length=1),
    max_chars: int = Query(default=12000, ge=200, le=24000),
    service: SessionArtifactService = Depends(get_session_artifact_service),
) -> StandardResponse[WorkspaceFilePreviewResponse]:
    _logger.info(
        "预览会话 workspace 文件: session_id=%s path=%s max_chars=%s",
        session_id,
        path,
        max_chars,
    )
    return ok(service.preview_workspace_file(session_id, path=path, max_chars=max_chars))


@router.get("/sessions/{session_id}/events", response_model=StandardResponse[list[EventView]])
async def get_session_events(
    session_id: str,
    service: SessionQueryService = Depends(get_session_query_service),
) -> StandardResponse[list[EventView]]:
    _logger.info("查询会话事件: session_id=%s", session_id)
    events = service.list_session_events(session_id)
    _logger.info("会话事件查询完成: session_id=%s event_count=%s", session_id, len(events))
    return ok([event_view(item) for item in events])


@router.delete("/sessions/{session_id}", response_model=StandardResponse[SessionDeleteResponse])
async def delete_session(
    session_id: str,
    service: SessionQueryService = Depends(get_session_query_service),
) -> StandardResponse[SessionDeleteResponse]:
    normalized = session_id.strip()
    _logger.info("删除会话请求: session_id=%s", normalized)
    await service.delete_session(normalized)
    return ok(SessionDeleteResponse(session_id=normalized, deleted=True))


@router.patch("/sessions/{session_id}", response_model=StandardResponse[SessionListItem])
async def patch_session(
    session_id: str,
    request: SessionUpdateRequest,
    service: SessionQueryService = Depends(get_session_query_service),
) -> StandardResponse[SessionListItem]:
    normalized = session_id.strip()
    _logger.info(
        "更新会话元数据请求: session_id=%s has_title=%s has_pin=%s",
        normalized,
        request.title is not None,
        request.is_pinned is not None,
    )
    updated = await service.update_session(normalized, request)
    return ok(session_item_view(updated))


@router.get("/memories", response_model=StandardResponse[list[MemoryView]])
async def get_memories(
    params: MemoryQueryParams = Depends(),
    service: MemoryQueryService = Depends(get_memory_query_service),
) -> StandardResponse[list[MemoryView]]:
    _logger.info(
        "查询记忆: request_agent=%s target_agent=%s query=%s limit=%s",
        params.agent_id,
        params.target_agent_id,
        params.q,
        params.limit,
    )
    items = service.list_memories(
        params.q,
        params.limit,
        request_agent_id=params.agent_id,
        target_agent_id=params.target_agent_id,
    )
    _logger.info(
        "记忆查询完成: request_agent=%s target_agent=%s query=%s result_count=%s",
        params.agent_id,
        params.target_agent_id,
        params.q,
        len(items),
    )
    return ok([memory_view(item) for item in items])


def _format_sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"
