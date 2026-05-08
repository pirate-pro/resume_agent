"""Infrastructure dependency providers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from app.api.dependencies.config import get_settings
from app.career.store import CareerProductStore
from app.infra.locks.session_lock_manager import SessionLockManager
from app.infra.storage.jsonl_session_repository import JsonlSessionRepository
from app.infra.storage.markdown_agent_document_repository import MarkdownAgentDocumentRepository
from app.infra.storage.markdown_skill_repository import MarkdownSkillRepository
from app.memory.file_store import FileMemoryStore
from app.state.stores.jsonl_file_store import JsonlFileStateStore

__all__ = [
    "get_agent_document_repository",
    "get_career_product_store",
    "get_lock_manager",
    "get_memory_store",
    "get_session_repository",
    "get_skill_repository",
    "get_state_store",
]


@lru_cache(maxsize=1)
def get_session_repository() -> JsonlSessionRepository:
    settings = get_settings()
    return JsonlSessionRepository(data_dir=settings.data_dir)


@lru_cache(maxsize=1)
def get_career_product_store() -> CareerProductStore:
    settings = get_settings()
    return CareerProductStore(root_dir=settings.data_dir / "career")


@lru_cache(maxsize=1)
def get_memory_store() -> FileMemoryStore:
    settings = get_settings()
    return FileMemoryStore(root_dir=settings.data_dir / "memory")


@lru_cache(maxsize=1)
def get_state_store() -> JsonlFileStateStore:
    settings = get_settings()
    return JsonlFileStateStore(root_dir=settings.data_dir / "state")


@lru_cache(maxsize=1)
def get_skill_repository() -> MarkdownSkillRepository:
    skills_dir = Path(__file__).resolve().parents[2] / "skills"
    return MarkdownSkillRepository(skills_dir=skills_dir)


@lru_cache(maxsize=1)
def get_agent_document_repository() -> MarkdownAgentDocumentRepository:
    agents_dir = Path(__file__).resolve().parents[2] / "agents"
    return MarkdownAgentDocumentRepository(agents_dir=agents_dir)


@lru_cache(maxsize=1)
def get_lock_manager() -> SessionLockManager:
    return SessionLockManager()
