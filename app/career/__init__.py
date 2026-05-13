"""Career product asset domain."""

from __future__ import annotations

from app.career.models import (
    CareerApplication,
    CareerProfile,
    CareerRecordStatus,
    JDAnalysis,
    JobFitReport,
    ResumeProfile,
    ResumeVersion,
)
from app.career.store import CareerProductStore
from app.career.workbench import CareerWorkbenchService

__all__ = [
    "CareerApplication",
    "CareerProductStore",
    "CareerProfile",
    "CareerRecordStatus",
    "CareerWorkbenchService",
    "JDAnalysis",
    "JobFitReport",
    "ResumeProfile",
    "ResumeVersion",
]
