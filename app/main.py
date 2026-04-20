from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.config.settings import get_settings
from app.core.db.session import create_all_if_needed
from app.core.middleware.audit import AuditMiddleware
from app.core.middleware.error_handler import install_exception_handlers
from app.core.middleware.logging import LoggingMiddleware
from app.core.middleware.request_id import RequestIdMiddleware
from app.tools.seed_jobs import seed_default_jobs
from app.web.routes import web_router


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    create_all_if_needed()
    if settings.auto_seed_jobs:
        seed_default_jobs()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, debug=settings.app_debug, lifespan=lifespan)
    install_exception_handlers(app)
    web_root = Path(__file__).resolve().parent / "web"

    if settings.request_id_enabled:
        app.add_middleware(RequestIdMiddleware)
    app.add_middleware(LoggingMiddleware)
    if settings.audit_log_enabled:
        app.add_middleware(AuditMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_prefix)
    app.include_router(web_router)
    app.mount("/assets", StaticFiles(directory=web_root / "assets"), name="assets")
    return app


app = create_app()
