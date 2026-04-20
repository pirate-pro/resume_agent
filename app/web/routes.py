from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

web_router = APIRouter(include_in_schema=False)
WEB_ROOT = Path(__file__).resolve().parent


@web_router.get("/")
def web_index() -> FileResponse:
    return FileResponse(WEB_ROOT / "index.html")
