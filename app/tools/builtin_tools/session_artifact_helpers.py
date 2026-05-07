"""Helper functions for session artifact tools."""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.errors import ToolExecutionError
from app.domain.models import SessionArtifact
from app.domain.protocols import SessionRepository

__all__ = [
    "collect_text_hits",
    "decide_artifact_access_plan",
    "ensure_session_artifact_text_ready",
    "require_session_artifact",
]

_logger = logging.getLogger(__name__)
_SMALL_ARTIFACT_TOKEN_THRESHOLD = 3000
_LARGE_ARTIFACT_TOKEN_THRESHOLD = 20000


def require_session_artifact(
    session_repository: SessionRepository,
    session_id: str,
    artifact_id: str,
) -> SessionArtifact:
    artifact = session_repository.get_session_artifact(session_id, artifact_id)
    if artifact is None:
        raise ToolExecutionError(f"Session artifact not found: artifact_id={artifact_id}")
    if artifact.visibility != "session_shared":
        raise ToolExecutionError(f"Session artifact is not shared: artifact_id={artifact_id}")
    return artifact


def ensure_session_artifact_text_ready(
    session_repository: SessionRepository,
    session_id: str,
    artifact: SessionArtifact,
) -> tuple[SessionArtifact, str]:
    if artifact.status == "ready" and artifact.text_relpath is not None:
        try:
            content = session_repository.read_session_artifact_text(session_id, artifact.artifact_id)
            return artifact, content
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "读取已解析 artifact 失败，尝试重新解析: session_id=%s artifact_id=%s error=%s",
                session_id,
                artifact.artifact_id,
                exc,
            )

    root = session_repository.get_session_root_path(session_id).resolve()
    storage_path = (root / artifact.storage_relpath).resolve()
    if not storage_path.is_relative_to(root):
        raise ToolExecutionError(f"Invalid artifact path for artifact_id={artifact.artifact_id}")
    if not storage_path.exists() or not storage_path.is_file():
        raise ToolExecutionError(f"Artifact file missing on disk: artifact_id={artifact.artifact_id}")

    extension = Path(artifact.title).suffix.lower().strip()
    parsed_text, parse_error = _parse_artifact_text(storage_path, extension)
    if parse_error is not None or parsed_text is None:
        if _should_mark_parse_failure(extension):
            failed_artifact = SessionArtifact(
                artifact_id=artifact.artifact_id,
                session_id=artifact.session_id,
                kind=artifact.kind,
                title=artifact.title,
                description=artifact.description,
                media_type=artifact.media_type,
                size_bytes=artifact.size_bytes,
                status="failed",
                visibility=artifact.visibility,
                owner_agent_id=artifact.owner_agent_id,
                source_type=artifact.source_type,
                source_event_id=artifact.source_event_id,
                created_at=artifact.created_at,
                updated_at=datetime.now(UTC),
                storage_relpath=artifact.storage_relpath,
                text_relpath=None,
                error=parse_error,
            )
            session_repository.add_or_update_session_artifact(failed_artifact)
        raise ToolExecutionError(parse_error or f"Failed to parse artifact: artifact_id={artifact.artifact_id}")

    parsed_path = storage_path.parent / "content.txt"
    parsed_path.write_text(parsed_text, encoding="utf-8")
    now = datetime.now(UTC)
    ready_artifact = SessionArtifact(
        artifact_id=artifact.artifact_id,
        session_id=artifact.session_id,
        kind=artifact.kind,
        title=artifact.title,
        description=artifact.description,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        status="ready",
        visibility=artifact.visibility,
        owner_agent_id=artifact.owner_agent_id,
        source_type=artifact.source_type,
        source_event_id=artifact.source_event_id,
        created_at=artifact.created_at,
        updated_at=now,
        storage_relpath=artifact.storage_relpath,
        text_relpath=str(parsed_path.resolve().relative_to(root)),
        error=None,
        text_char_count=len(parsed_text),
        token_estimate=_estimate_tokens_from_text(parsed_text),
        parsed_at=now,
    )
    session_repository.add_or_update_session_artifact(ready_artifact)
    return ready_artifact, parsed_text


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


def decide_artifact_access_plan(artifact: SessionArtifact, user_goal: str | None) -> dict[str, Any]:
    goal = (user_goal or "").strip().lower()
    token_estimate = _estimate_tokens_from_artifact(artifact)

    if artifact.media_type.startswith("image/"):
        return {
            "strategy": "vision_required",
            "reason": "image_artifact_detected",
            "estimated_tokens": token_estimate,
            "steps": [
                "确认是否有视觉模型工具可用",
                "若无视觉模型，提示用户切换到支持图片理解的模型",
            ],
        }

    if artifact.status == "failed":
        return {
            "strategy": "unreadable",
            "reason": "parse_failed",
            "estimated_tokens": token_estimate,
            "steps": [
                "先告知 artifact 解析失败",
                "提供可执行建议：重传、转文本、或缩小到可解析格式",
            ],
        }

    if goal in {"find_fact", "quote_exact", "locate", "extract", "compare", "troubleshoot", "debug"}:
        return {
            "strategy": "search_then_read",
            "reason": "goal_requires_precision",
            "estimated_tokens": token_estimate,
            "steps": [
                "调用 session_search_artifact 定位命中片段",
                "再调用 session_read_artifact 对命中附近做精读",
            ],
        }

    if token_estimate <= _SMALL_ARTIFACT_TOKEN_THRESHOLD:
        return {
            "strategy": "direct_read",
            "reason": "small_artifact",
            "estimated_tokens": token_estimate,
            "steps": [
                "调用 session_read_artifact 直接读取主体内容",
                "必要时再调用 session_search_artifact 补充定位细节",
            ],
        }

    if token_estimate <= _LARGE_ARTIFACT_TOKEN_THRESHOLD:
        return {
            "strategy": "search_then_read",
            "reason": "medium_artifact",
            "estimated_tokens": token_estimate,
            "steps": [
                "先调用 session_search_artifact 缩小范围",
                "再调用 session_read_artifact 读取关键片段",
            ],
        }

    return {
        "strategy": "focused_search_then_chunked_read",
        "reason": "large_artifact",
        "estimated_tokens": token_estimate,
        "steps": [
            "先调用 session_search_artifact 定位最相关片段",
            "分块调用 session_read_artifact（offset + max_chars）精读",
            "若范围仍过大，要求用户给出章节/关键词进一步收敛",
        ],
    }


def _parse_artifact_text(path: Path, extension: str) -> tuple[str | None, str | None]:
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
        return None, f"Failed to parse artifact text: {exc}"


def _should_mark_parse_failure(extension: str) -> bool:
    return extension in {".txt", ".md", ".markdown", ".json", ".pdf"}


def _estimate_tokens_from_text(text: str) -> int:
    char_count = len(text)
    if char_count <= 0:
        return 1
    return max(1, (char_count + 3) // 4)


def _estimate_tokens_from_artifact(artifact: SessionArtifact) -> int:
    if artifact.token_estimate is not None and artifact.token_estimate > 0:
        return artifact.token_estimate
    if artifact.text_char_count is not None and artifact.text_char_count > 0:
        return max(1, (artifact.text_char_count + 3) // 4)
    return max(1, (artifact.size_bytes + 3) // 4)
