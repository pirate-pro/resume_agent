"""Helper functions for uploaded session file tools."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import SessionFile
from app.domain.protocols import SessionRepository

__all__ = [
    "collect_text_hits",
    "decide_file_access_plan",
    "ensure_session_file_text_ready",
    "require_session_file",
    "serialize_file_listing",
]

_logger = logging.getLogger(__name__)
_SMALL_FILE_TOKEN_THRESHOLD = 3000
_LARGE_FILE_TOKEN_THRESHOLD = 20000


def serialize_file_listing(item: SessionFile, *, active_file_ids: set[str]) -> dict[str, Any]:
    return {
        "file_id": item.file_id,
        "filename": item.filename,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "status": item.status,
        "uploaded_at": item.uploaded_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "error": item.error,
        "is_active": item.file_id in active_file_ids,
        "text_ready": item.status == "ready" and item.text_relpath is not None,
        "parsed_char_count": item.parsed_char_count,
        "parsed_token_estimate": item.parsed_token_estimate,
        "parsed_at": None
        if item.parsed_at is None
        else item.parsed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "recommended_access_plan": decide_file_access_plan(file_record=item, user_goal=None),
    }


def require_session_file(session_repository: SessionRepository, session_id: str, file_id: str) -> SessionFile:
    file_record = session_repository.get_session_file(session_id, file_id)
    if file_record is None:
        raise ToolExecutionError(f"Session file not found: file_id={file_id}")
    return file_record


def ensure_session_file_text_ready(
    session_repository: SessionRepository,
    session_id: str,
    file_record: SessionFile,
) -> tuple[SessionFile, str]:
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

    root = session_repository.get_session_root_path(session_id).resolve()
    storage_path = (root / file_record.storage_relpath).resolve()
    if not storage_path.is_relative_to(root):
        raise ToolExecutionError(f"Invalid file path for file_id={file_record.file_id}")
    if not storage_path.exists() or not storage_path.is_file():
        raise ToolExecutionError(f"Uploaded file missing on disk: file_id={file_record.file_id}")

    extension = Path(file_record.filename).suffix.lower().strip()
    parsed_text, parse_error = _parse_file_text(storage_path, extension)
    if parse_error is not None or parsed_text is None:
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


def collect_text_hits(text: str, query: str, top_k: int, window_chars: int) -> list[dict[str, Any]]:
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


def decide_file_access_plan(file_record: SessionFile, user_goal: str | None) -> dict[str, Any]:
    goal = (user_goal or "").strip().lower()
    token_estimate = _estimate_tokens_from_file(file_record)

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


def _estimate_tokens_from_text(text: str) -> int:
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
