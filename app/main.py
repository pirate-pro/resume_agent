"""FastAPI application entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.deps import get_settings
from app.core.logging import configure_logging
from app.web.routes import router as web_router

__all__ = ["app"]

settings = get_settings()
configure_logging(settings.debug)

app = FastAPI(title=settings.app_name, debug=settings.debug)

# Allow local Flutter Web dev servers (different ports) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(web_router)
app.include_router(chat_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
