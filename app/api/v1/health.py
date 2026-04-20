from pathlib import Path

from fastapi import APIRouter
from sqlalchemy import text

from app.application.dto.schemas import HealthResponse
from app.core.config.settings import get_settings
from app.core.db.session import SessionLocal

router = APIRouter()


def _run_checks() -> dict:
    settings = get_settings()
    checks = {
        "database": False,
        "file_root": False,
        "artifact_root": False,
    }
    try:
        with SessionLocal() as session:
            session.execute(text("select 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    Path(settings.file_root_path).mkdir(parents=True, exist_ok=True)
    Path(settings.artifact_root_path).mkdir(parents=True, exist_ok=True)
    checks["file_root"] = Path(settings.file_root_path).is_dir()
    checks["artifact_root"] = Path(settings.artifact_root_path).is_dir()
    return checks


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks = _run_checks()
    status = "ok" if all(checks.values()) else "degraded"
    return HealthResponse(status=status, checks=checks)


@router.get("/ready", response_model=HealthResponse)
def ready() -> HealthResponse:
    checks = _run_checks()
    status = "ready" if all(checks.values()) else "not_ready"
    return HealthResponse(status=status, checks=checks)
