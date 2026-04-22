"""Built-in tools for memory and workspace access."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.errors import StorageError, ToolExecutionError, ValidationError
from app.memory.contracts import MemoryFacade
from app.memory.intake import build_candidate_request
from app.memory.models import MemoryConsolidateRequest, MemoryReadRequest
from app.domain.models import MemoryItem, SessionFile, ToolDefinition, ToolExecutionResult
from app.domain.protocols import SessionRepository

__all__ = [
    "MemorySearchTool",
    "MemoryWriteTool",
    "SessionListFilesTool",
    "SessionPlanFileAccessTool",
    "SessionReadFileTool",
    "SessionSearchFileTool",
    "WorkspaceReadFileTool",
    "WorkspaceWriteFileTool",
]
_logger = logging.getLogger(__name__)
_SMALL_FILE_TOKEN_THRESHOLD = 3000
_LARGE_FILE_TOKEN_THRESHOLD = 20000


class MemoryWriteTool:
    """Write long-term memory entries."""

    def __init__(
        self,
        memory_facade: MemoryFacade,
        default_agent_id: str = "agent_main",
    ) -> None:
        self._memory_facade = memory_facade
        self._default_agent_id = default_agent_id.strip() if default_agent_id.strip() else "agent_main"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_write",
            description=(
                "Write a memory candidate. Default route is agent_short. "
                "Use tags like preference/constraint/long_term for agent_long, "
                "and shared/global/cross_agent for shared_long candidate."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": [],
                    },
                },
                "required": ["content"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        content = _require_non_empty_argument(arguments, "content")
        tags = _normalize_tags(arguments.get("tags", []))
        _logger.debug("执行 memory_write: session_id=%s tags=%s content_len=%s", session_id, len(tags), len(content))
        request = build_candidate_request(
            agent_id=self._default_agent_id,
            session_id=session_id,
            content=content,
            tags=tags,
            source_event_id=None,
            source="memory_write_tool",
        )
        candidate = self._memory_facade.write_candidate(request)
        consolidate_result = self._memory_facade.consolidate(MemoryConsolidateRequest(max_candidates=8))
        resolved_memory_id = (
            consolidate_result.written_memory_ids[0]
            if consolidate_result.written_memory_ids
            else f"cand_{candidate.candidate_id}"
        )
        return ToolExecutionResult(
            tool_name="memory_write",
            success=True,
            content=json.dumps(
                {
                    "memory_id": resolved_memory_id,
                    "candidate_id": candidate.candidate_id,
                    "written_records": consolidate_result.written_records,
                },
                ensure_ascii=False,
            ),
        )


class MemorySearchTool:
    """Search memory items by query."""

    def __init__(self, memory_facade: MemoryFacade, default_agent_id: str = "agent_main") -> None:
        self._memory_facade = memory_facade
        self._default_agent_id = default_agent_id.strip() if default_agent_id.strip() else "agent_main"

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="memory_search",
            description="Search memory items using plain-text matching.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
                },
                "required": ["query"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        query = _require_non_empty_argument(arguments, "query")
        raw_limit = arguments.get("limit", 5)
        if not isinstance(raw_limit, int) or raw_limit <= 0:
            raise ToolExecutionError("'limit' must be a positive integer.")
        limit = min(raw_limit, 20)
        bundle = self._memory_facade.read_context(
            MemoryReadRequest(
                agent_id=self._default_agent_id,
                session_id=session_id,
                query=query,
                limit=limit,
                token_budget=max(600, limit * 280),
            )
        )
        hits = bundle.items
        _logger.debug("执行 memory_search: session_id=%s query=%s hit_count=%s", session_id, query, len(hits))
        payload = [
            {
                "memory_id": item.memory_id,
                "content": item.content,
                "tags": item.tags,
                "scope": item.scope.value,
                "confidence": item.confidence,
            }
            for item in hits
        ]
        return ToolExecutionResult(
            tool_name="memory_search",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class WorkspaceWriteFileTool:
    """Write a text file under session workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_write_file",
            description="Write content into a session workspace file.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        relative_path = _require_non_empty_argument(arguments, "path")
        content = _require_non_empty_argument(arguments, "content")
        workspace = self._session_repository.get_workspace_path(session_id)
        target = _resolve_workspace_path(workspace, relative_path)
        _logger.debug("执行 workspace_write_file: session_id=%s path=%s", session_id, relative_path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to write file: {exc}") from exc
        return ToolExecutionResult(
            tool_name="workspace_write_file",
            success=True,
            content=f"Wrote file: {relative_path}",
        )


class WorkspaceReadFileTool:
    """Read a text file under session workspace."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="workspace_read_file",
            description=(
                "Read content from file with workspace-first lookup. "
                "Workspace is data/sessions/<session_id>/workspace. "
                "If missing in workspace, search parent directories upward to filesystem root."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        relative_path = _require_non_empty_argument(arguments, "path")
        workspace = self._session_repository.get_workspace_path(session_id).resolve()
        target = _find_file_with_workspace_fallback(workspace, relative_path)
        if target is None:
            raise ToolExecutionError(
                "File does not exist after workspace-first lookup. "
                f"path={relative_path} workspace={workspace}"
            )
        _logger.debug(
            "执行 workspace_read_file: session_id=%s path=%s resolved_path=%s workspace=%s",
            session_id,
            relative_path,
            target,
            workspace,
        )
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolExecutionError(f"Failed to read file: {exc}") from exc
        return ToolExecutionResult(tool_name="workspace_read_file", success=True, content=content or "(empty)")


class SessionListFilesTool:
    """List uploaded files for current session."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_list_files",
            description="List uploaded files in current session, including active status and parse status.",
            parameters_schema={
                "type": "object",
                "properties": {},
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        if not isinstance(arguments, dict):
            raise ToolExecutionError("Tool arguments must be an object.")
        files = self._session_repository.list_session_files(session_id)
        active_file_ids = self._session_repository.get_active_file_ids(session_id)
        active_set = set(active_file_ids)
        payload = {
            "session_id": session_id,
            "active_file_ids": active_file_ids,
            "files": [
                {
                    "file_id": item.file_id,
                    "filename": item.filename,
                    "media_type": item.media_type,
                    "size_bytes": item.size_bytes,
                    "status": item.status,
                    "uploaded_at": item.uploaded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    "error": item.error,
                    "is_active": item.file_id in active_set,
                    "text_ready": item.status == "ready" and item.text_relpath is not None,
                    "parsed_char_count": item.parsed_char_count,
                    "parsed_token_estimate": item.parsed_token_estimate,
                    "parsed_at": None
                    if item.parsed_at is None
                    else item.parsed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    # 仅基于元数据的快速建议，具体问题仍建议调用 session_plan_file_access。
                    "recommended_access_plan": _decide_file_access_plan(file_record=item, user_goal=None),
                }
                for item in files
            ],
        }
        return ToolExecutionResult(
            tool_name="session_list_files",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionReadFileTool:
    """Read session file text with lazy parse."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_read_file",
            description=(
                "Read text content from an uploaded session file by file_id. "
                "If file text is not parsed yet, parse lazily then read."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "offset": {"type": "integer", "default": 0, "minimum": 0},
                    "max_chars": {"type": "integer", "default": 3000, "minimum": 200, "maximum": 12000},
                },
                "required": ["file_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        file_id = _require_non_empty_argument(arguments, "file_id")
        offset = _parse_non_negative_int(arguments.get("offset", 0), field_name="offset")
        max_chars = _parse_positive_int(arguments.get("max_chars", 3000), field_name="max_chars")
        max_chars = min(max_chars, 12000)
        file_record = _require_session_file(self._session_repository, session_id, file_id)
        # 懒解析入口：仅当工具实际读取时才确保文本可用，避免上传阶段占用上下文与计算。
        updated_file, text = _ensure_session_file_text_ready(self._session_repository, session_id, file_record)
        snippet = text[offset : offset + max_chars] if offset < len(text) else ""
        payload = {
            "file_id": updated_file.file_id,
            "filename": updated_file.filename,
            "media_type": updated_file.media_type,
            "status": updated_file.status,
            "total_chars": len(text),
            "offset": offset,
            "returned_chars": len(snippet),
            "truncated": offset + max_chars < len(text),
            "content": snippet,
        }
        return ToolExecutionResult(
            tool_name="session_read_file",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionPlanFileAccessTool:
    """Plan a recommended file reading strategy from metadata."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_plan_file_access",
            description=(
                "Return recommended reading strategy for one uploaded session file "
                "based on metadata and optional user_goal."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "user_goal": {
                        "type": "string",
                        "description": (
                            "Optional user intent hint, e.g. summarize, find_fact, quote_exact, compare, troubleshoot."
                        ),
                    },
                },
                "required": ["file_id"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        file_id = _require_non_empty_argument(arguments, "file_id")
        raw_goal = arguments.get("user_goal")
        user_goal = raw_goal.strip() if isinstance(raw_goal, str) and raw_goal.strip() else None

        file_record = _require_session_file(self._session_repository, session_id, file_id)
        plan = _decide_file_access_plan(file_record=file_record, user_goal=user_goal)
        payload = {
            "file_id": file_record.file_id,
            "filename": file_record.filename,
            "media_type": file_record.media_type,
            "status": file_record.status,
            "size_bytes": file_record.size_bytes,
            "parsed_char_count": file_record.parsed_char_count,
            "parsed_token_estimate": file_record.parsed_token_estimate,
            "user_goal": user_goal,
            "plan": plan,
        }
        return ToolExecutionResult(
            tool_name="session_plan_file_access",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )


class SessionSearchFileTool:
    """Search keyword in parsed text for one uploaded file."""

    def __init__(self, session_repository: SessionRepository) -> None:
        self._session_repository = session_repository

    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="session_search_file",
            description=(
                "Search keyword in one uploaded session file by file_id. "
                "Return snippet hits with nearby context."
            ),
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_id": {"type": "string"},
                    "query": {"type": "string"},
                    "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 8},
                    "window_chars": {"type": "integer", "default": 160, "minimum": 40, "maximum": 800},
                },
                "required": ["file_id", "query"],
            },
        )

    def execute(self, arguments: dict[str, Any], session_id: str) -> ToolExecutionResult:
        _validate_session_id(session_id)
        file_id = _require_non_empty_argument(arguments, "file_id")
        query = _require_non_empty_argument(arguments, "query")
        top_k = min(_parse_positive_int(arguments.get("top_k", 3), field_name="top_k"), 8)
        window_chars = min(_parse_positive_int(arguments.get("window_chars", 160), field_name="window_chars"), 800)

        file_record = _require_session_file(self._session_repository, session_id, file_id)
        # 搜索同样走懒解析，保证检索永远基于最新可读文本。
        updated_file, text = _ensure_session_file_text_ready(self._session_repository, session_id, file_record)
        hits = _collect_text_hits(text=text, query=query, top_k=top_k, window_chars=window_chars)
        payload = {
            "file_id": updated_file.file_id,
            "filename": updated_file.filename,
            "query": query,
            "hit_count": len(hits),
            "hits": hits,
        }
        return ToolExecutionResult(
            tool_name="session_search_file",
            success=True,
            content=json.dumps(payload, ensure_ascii=False),
        )



def _validate_session_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValidationError("session_id must be a non-empty string.")
    return session_id.strip()



def _require_non_empty_argument(arguments: dict[str, Any], key: str) -> str:
    if not isinstance(arguments, dict):
        raise ToolExecutionError("Tool arguments must be an object.")
    raw_value = arguments.get(key)
    if not isinstance(raw_value, str) or not raw_value.strip():
        raise ToolExecutionError(f"'{key}' must be a non-empty string.")
    return raw_value.strip()



def _normalize_tags(raw_tags: Any) -> list[str]:
    if raw_tags is None:
        return []
    if not isinstance(raw_tags, list):
        raise ToolExecutionError("'tags' must be a list of strings.")
    normalized: list[str] = []
    for tag in raw_tags:
        if not isinstance(tag, str) or not tag.strip():
            raise ToolExecutionError("each tag must be a non-empty string.")
        normalized.append(tag.strip())
    return normalized



def _resolve_workspace_path(workspace: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    workspace_resolved = workspace.resolve()
    target = (workspace_resolved / candidate).resolve()
    if not target.is_relative_to(workspace_resolved):
        raise ToolExecutionError("Path traversal is not allowed.")
    return target


def _find_file_with_workspace_fallback(workspace: Path, relative_path: str) -> Path | None:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ToolExecutionError("Absolute paths are not allowed.")
    if ".." in candidate.parts:
        raise ToolExecutionError("Path traversal is not allowed.")

    # 查找顺序：workspace -> workspace 的父目录 ... -> 文件系统根目录
    search_roots = [workspace, *list(workspace.parents)]
    for root in search_roots:
        target = root / candidate
        if target.exists() and target.is_file():
            return target
    return None


def _parse_non_negative_int(raw: Any, field_name: str) -> int:
    if not isinstance(raw, int) or raw < 0:
        raise ToolExecutionError(f"'{field_name}' must be a non-negative integer.")
    return raw


def _parse_positive_int(raw: Any, field_name: str) -> int:
    if not isinstance(raw, int) or raw <= 0:
        raise ToolExecutionError(f"'{field_name}' must be a positive integer.")
    return raw


def _require_session_file(session_repository: SessionRepository, session_id: str, file_id: str) -> SessionFile:
    file_record = session_repository.get_session_file(session_id, file_id)
    if file_record is None:
        raise ToolExecutionError(f"Session file not found: file_id={file_id}")
    return file_record


def _ensure_session_file_text_ready(
    session_repository: SessionRepository,
    session_id: str,
    file_record: SessionFile,
) -> tuple[SessionFile, str]:
    # 优先复用已解析缓存，命中则直接返回。
    if file_record.status == "ready" and file_record.text_relpath is not None:
        try:
            content = session_repository.read_session_file_text(session_id, file_record.file_id)
            return file_record, content
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "读取已解析文件失败，尝试重新解析: session_id=%s file_id=%s error=%s",
                session_id,
                file_record.file_id,
                exc,
            )

    # 缓存不可用时，回到原始上传文件重新解析（这就是懒加载的核心路径）。
    root = session_repository.get_session_root_path(session_id).resolve()
    storage_path = (root / file_record.storage_relpath).resolve()
    if not storage_path.is_relative_to(root):
        raise ToolExecutionError(f"Invalid file path for file_id={file_record.file_id}")
    if not storage_path.exists() or not storage_path.is_file():
        raise ToolExecutionError(f"Uploaded file missing on disk: file_id={file_record.file_id}")

    extension = Path(file_record.filename).suffix.lower().strip()
    parsed_text, parse_error = _parse_file_text(storage_path, extension)
    if parse_error is not None or parsed_text is None:
        # 可解析文本类型失败时，回写 failed，避免后续重复盲解析。
        if _should_mark_parse_failure(extension):
            failed_record = SessionFile(
                file_id=file_record.file_id,
                session_id=file_record.session_id,
                filename=file_record.filename,
                media_type=file_record.media_type,
                size_bytes=file_record.size_bytes,
                status="failed",
                uploaded_at=file_record.uploaded_at,
                storage_relpath=file_record.storage_relpath,
                text_relpath=None,
                error=parse_error,
                parsed_char_count=None,
                parsed_token_estimate=None,
                parsed_at=None,
            )
            session_repository.add_or_update_session_file(failed_record)
        raise ToolExecutionError(parse_error or f"Failed to parse file: file_id={file_record.file_id}")

    # 解析成功后写入 .parsed 缓存，并把文件状态更新为 ready。
    workspace = session_repository.get_workspace_path(session_id)
    parsed_dir = workspace / ".parsed"
    parsed_dir.mkdir(parents=True, exist_ok=True)
    parsed_path = parsed_dir / f"{file_record.file_id}.txt"
    parsed_path.write_text(parsed_text, encoding="utf-8")

    ready_record = SessionFile(
        file_id=file_record.file_id,
        session_id=file_record.session_id,
        filename=file_record.filename,
        media_type=file_record.media_type,
        size_bytes=file_record.size_bytes,
        status="ready",
        uploaded_at=file_record.uploaded_at,
        storage_relpath=file_record.storage_relpath,
        text_relpath=str(parsed_path.resolve().relative_to(root)),
        error=None,
        parsed_char_count=len(parsed_text),
        parsed_token_estimate=_estimate_tokens_from_text(parsed_text),
        parsed_at=datetime.now(UTC),
    )
    session_repository.add_or_update_session_file(ready_record)
    return ready_record, parsed_text


def _parse_file_text(path: Path, extension: str) -> tuple[str | None, str | None]:
    try:
        if extension in {".txt", ".md", ".markdown"}:
            return path.read_text(encoding="utf-8"), None
        if extension == ".json":
            raw = json.loads(path.read_text(encoding="utf-8"))
            return json.dumps(raw, ensure_ascii=False, indent=2), None
        if extension == ".pdf":
            proc = subprocess.run(
                ["pdftotext", str(path), "-"],
                check=False,
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "unknown error").strip()
                return None, f"Failed to parse PDF with pdftotext: {detail}"
            content = proc.stdout.strip()
            if not content:
                return None, "Parsed PDF content is empty."
            return content, None
        if extension in {".png", ".jpg", ".jpeg", ".webp"}:
            return None, "Image parsing requires vision model support, which is not enabled in text tools."
        return None, f"Unsupported text parser for extension: {extension or '(none)'}"
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return None, f"Failed to parse file text: {exc}"


def _should_mark_parse_failure(extension: str) -> bool:
    return extension in {".txt", ".md", ".markdown", ".json", ".pdf"}


def _collect_text_hits(text: str, query: str, top_k: int, window_chars: int) -> list[dict[str, Any]]:
    lowered_text = text.lower()
    lowered_query = query.lower()
    if not lowered_query:
        return []

    hits: list[dict[str, Any]] = []
    cursor = 0
    while len(hits) < top_k:
        index = lowered_text.find(lowered_query, cursor)
        if index < 0:
            break
        start = max(0, index - window_chars)
        end = min(len(text), index + len(query) + window_chars)
        snippet = text[start:end].strip()
        hits.append(
            {
                "start_index": index,
                "end_index": index + len(query),
                "snippet": snippet,
            }
        )
        cursor = index + len(query)
    return hits


def _estimate_tokens_from_text(text: str) -> int:
    # 近似估算：英文约 4 字符/token，中文会更密集但这里用于策略粗分桶即可。
    char_count = len(text)
    if char_count <= 0:
        return 1
    return max(1, (char_count + 3) // 4)


def _estimate_tokens_from_file(file_record: SessionFile) -> int:
    if file_record.parsed_token_estimate is not None and file_record.parsed_token_estimate > 0:
        return file_record.parsed_token_estimate
    if file_record.parsed_char_count is not None and file_record.parsed_char_count > 0:
        return max(1, (file_record.parsed_char_count + 3) // 4)
    return max(1, (file_record.size_bytes + 3) // 4)


def _decide_file_access_plan(file_record: SessionFile, user_goal: str | None) -> dict[str, Any]:
    goal = (user_goal or "").strip().lower()
    token_estimate = _estimate_tokens_from_file(file_record)

    # 图片先给出边界：当前文本工具不能直接理解图片，需要视觉模型工具链。
    if file_record.media_type.startswith("image/"):
        return {
            "strategy": "vision_required",
            "reason": "image_file_detected",
            "estimated_tokens": token_estimate,
            "steps": [
                "确认是否有视觉模型工具可用",
                "若无视觉模型，提示用户切换到支持图片理解的模型",
            ],
        }

    if file_record.status == "failed":
        return {
            "strategy": "unreadable",
            "reason": "parse_failed",
            "estimated_tokens": token_estimate,
            "steps": [
                "先告知文件解析失败",
                "提供可执行建议：重传、转文本、或缩小到可解析格式",
            ],
        }

    # 对于事实查找/精确引用类问题，即便文件小，也优先搜索定位后再读。
    if goal in {
        "find_fact",
        "quote_exact",
        "locate",
        "extract",
        "compare",
        "troubleshoot",
        "debug",
    }:
        return {
            "strategy": "search_then_read",
            "reason": "goal_requires_precision",
            "estimated_tokens": token_estimate,
            "steps": [
                "调用 session_search_file 定位命中片段",
                "再调用 session_read_file 对命中附近做精读",
            ],
        }

    if token_estimate <= _SMALL_FILE_TOKEN_THRESHOLD:
        return {
            "strategy": "direct_read",
            "reason": "small_file",
            "estimated_tokens": token_estimate,
            "steps": [
                "调用 session_read_file 直接读取主体内容",
                "必要时再调用 session_search_file 补充定位细节",
            ],
        }

    if token_estimate <= _LARGE_FILE_TOKEN_THRESHOLD:
        return {
            "strategy": "search_then_read",
            "reason": "medium_file",
            "estimated_tokens": token_estimate,
            "steps": [
                "先调用 session_search_file 缩小范围",
                "再调用 session_read_file 读取关键片段",
            ],
        }

    return {
        "strategy": "focused_search_then_chunked_read",
        "reason": "large_file",
        "estimated_tokens": token_estimate,
        "steps": [
            "先调用 session_search_file 定位最相关片段",
            "分块调用 session_read_file（offset + max_chars）精读",
            "若范围仍过大，要求用户给出章节/关键词进一步收敛",
        ],
    }
