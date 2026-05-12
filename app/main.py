"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.career import router as career_router
from app.api.chat import router as chat_router
from app.api.knowledge import admin_router as knowledge_admin_router
from app.api.knowledge import router as knowledge_router
from app.api.learning import admin_router as learning_admin_router
from app.api.learning import router as learning_router
from app.api.notes import router as notes_router
from app.api.deps import get_chat_service, get_mid_term_flusher, get_mid_term_flush_worker, get_settings
from app.api.errors import app_error_handler, http_exception_handler, request_validation_error_handler
from app.api.responses import ok
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.schemas.common import StandardResponse
from app.web.routes import router as web_router

__all__ = ["app"]

settings = get_settings()
configure_logging(settings.debug)


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    worker = get_mid_term_flush_worker()
    chat_service = get_chat_service()
    worker_enabled = settings.mid_term_flush_worker_enabled
    if worker_enabled:
        await worker.start()
    try:
        yield
    finally:
        if worker_enabled:
            await worker.stop()
        await chat_service.wait_for_background_tasks()


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=_lifespan)
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, request_validation_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(web_router)
app.include_router(chat_router)
app.include_router(career_router)
app.include_router(notes_router)
app.include_router(knowledge_router)
app.include_router(knowledge_admin_router)
app.include_router(learning_router)
app.include_router(learning_admin_router)


@app.get("/health", response_model=StandardResponse[dict[str, Any]])
def health() -> StandardResponse[dict[str, Any]]:
    summary = _collect_mid_term_health_summary()
    status = "ok" if "error" not in summary else "degraded"
    return ok({
        "status": status,
        "mid_term_flush": summary,
    })


def _collect_mid_term_health_summary() -> dict[str, Any]:
    worker_enabled = settings.mid_term_flush_worker_enabled
    try:
        metrics = get_mid_term_flusher().collect_job_metrics()
    except Exception as exc:  # noqa: BLE001
        return {
            "worker_enabled": worker_enabled,
            "error": str(exc)[:240],
        }
    return {
        "worker_enabled": worker_enabled,
        "queue": {
            "targets": metrics.target_count,
            "total": metrics.total_jobs,
            "due": metrics.due_jobs,
            "retry": metrics.retry_jobs,
            "deferred": metrics.deferred_jobs,
            "succeeded": metrics.succeeded_jobs,
        },
    }
