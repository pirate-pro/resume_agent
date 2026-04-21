"""Routes for serving local frontend assets."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

__all__ = ["router"]

router = APIRouter(tags=["web"])

_WEB_DIR = Path(__file__).resolve().parent
_ASSETS_DIR = _WEB_DIR / "assets"
_INDEX_FILE = _WEB_DIR / "index.html"


@router.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(_INDEX_FILE, headers=_no_cache_headers())


@router.get("/assets/{asset_path:path}", include_in_schema=False)
def asset(asset_path: str) -> FileResponse:
    resolved = _resolve_asset_path(asset_path)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="asset not found")
    return FileResponse(resolved, headers=_no_cache_headers())


def _resolve_asset_path(asset_path: str) -> Path:
    candidate = Path(asset_path)
    if candidate.is_absolute():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid asset path")
    resolved_base = _ASSETS_DIR.resolve()
    resolved_target = (resolved_base / candidate).resolve()
    if not resolved_target.is_relative_to(resolved_base):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid asset path")
    return resolved_target


def _no_cache_headers() -> dict[str, str]:
    return {
        "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
        "Pragma": "no-cache",
    }
