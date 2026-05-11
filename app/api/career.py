"""Career product HTTP endpoints."""

from __future__ import annotations

from typing import TypeVar

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import get_career_product_store
from app.api.presenters import (
    career_application_view,
    career_profile_view,
    jd_analysis_view,
    job_fit_report_view,
    resume_profile_view,
    resume_version_view,
)
from app.api.responses import ok
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
from app.schemas.career import (
    CareerApplicationView,
    CareerProfileView,
    JDAnalysisView,
    JobFitReportView,
    ResumeProfileView,
    ResumeVersionView,
)
from app.schemas.common import StandardResponse

__all__ = ["router"]

router = APIRouter(prefix="/api/career", tags=["career"])
_RecordT = TypeVar(
    "_RecordT",
    ResumeProfile,
    CareerProfile,
    JDAnalysis,
    JobFitReport,
    ResumeVersion,
    CareerApplication,
)


@router.get("/resumes", response_model=StandardResponse[list[ResumeProfileView]])
def list_resume_profiles(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[ResumeProfileView]]:
    return ok([
        resume_profile_view(item)
        for item in store.list_resume_profiles(include_archived=include_archived)
    ])


@router.get("/resumes/{resume_profile_id}", response_model=StandardResponse[ResumeProfileView])
def get_resume_profile(
    resume_profile_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[ResumeProfileView]:
    record = _require_visible(
        store.get_resume_profile(resume_profile_id),
        include_archived=include_archived,
        record_type="ResumeProfile",
        record_id=resume_profile_id,
    )
    return ok(resume_profile_view(record))


@router.get("/profile", response_model=StandardResponse[CareerProfileView])
def get_default_career_profile(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[CareerProfileView]:
    record = _require_visible(
        store.get_career_profile(),
        include_archived=include_archived,
        record_type="CareerProfile",
        record_id="career_profile_default",
    )
    return ok(career_profile_view(record))


@router.get("/profiles", response_model=StandardResponse[list[CareerProfileView]])
def list_career_profiles(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[CareerProfileView]]:
    return ok([
        career_profile_view(item)
        for item in store.list_career_profiles(include_archived=include_archived)
    ])


@router.get("/profiles/{career_profile_id}", response_model=StandardResponse[CareerProfileView])
def get_career_profile(
    career_profile_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[CareerProfileView]:
    record = _require_visible(
        store.get_career_profile(career_profile_id),
        include_archived=include_archived,
        record_type="CareerProfile",
        record_id=career_profile_id,
    )
    return ok(career_profile_view(record))


@router.get("/jobs", response_model=StandardResponse[list[JDAnalysisView]])
def list_jd_analyses(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[JDAnalysisView]]:
    return ok([
        jd_analysis_view(item)
        for item in store.list_jd_analyses(include_archived=include_archived)
    ])


@router.get("/jobs/{jd_analysis_id}", response_model=StandardResponse[JDAnalysisView])
def get_jd_analysis(
    jd_analysis_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[JDAnalysisView]:
    record = _require_visible(
        store.get_jd_analysis(jd_analysis_id),
        include_archived=include_archived,
        record_type="JDAnalysis",
        record_id=jd_analysis_id,
    )
    return ok(jd_analysis_view(record))


@router.get("/job-fit-reports", response_model=StandardResponse[list[JobFitReportView]])
def list_job_fit_reports(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[JobFitReportView]]:
    return ok([
        job_fit_report_view(item)
        for item in store.list_job_fit_reports(include_archived=include_archived)
    ])


@router.get("/job-fit-reports/{job_fit_report_id}", response_model=StandardResponse[JobFitReportView])
def get_job_fit_report(
    job_fit_report_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[JobFitReportView]:
    record = _require_visible(
        store.get_job_fit_report(job_fit_report_id),
        include_archived=include_archived,
        record_type="JobFitReport",
        record_id=job_fit_report_id,
    )
    return ok(job_fit_report_view(record))


@router.get("/resume-versions", response_model=StandardResponse[list[ResumeVersionView]])
def list_resume_versions(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[ResumeVersionView]]:
    return ok([
        resume_version_view(item)
        for item in store.list_resume_versions(include_archived=include_archived)
    ])


@router.get("/resume-versions/{resume_version_id}", response_model=StandardResponse[ResumeVersionView])
def get_resume_version(
    resume_version_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[ResumeVersionView]:
    record = _require_visible(
        store.get_resume_version(resume_version_id),
        include_archived=include_archived,
        record_type="ResumeVersion",
        record_id=resume_version_id,
    )
    return ok(resume_version_view(record))


@router.get("/applications", response_model=StandardResponse[list[CareerApplicationView]])
def list_career_applications(
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[list[CareerApplicationView]]:
    return ok([
        career_application_view(item)
        for item in store.list_career_applications(include_archived=include_archived)
    ])


@router.get("/applications/{application_id}", response_model=StandardResponse[CareerApplicationView])
def get_career_application(
    application_id: str,
    include_archived: bool = Query(default=False),
    store: CareerProductStore = Depends(get_career_product_store),
) -> StandardResponse[CareerApplicationView]:
    record = _require_visible(
        store.get_career_application(application_id),
        include_archived=include_archived,
        record_type="CareerApplication",
        record_id=application_id,
    )
    return ok(career_application_view(record))


def _require_visible(
    record: _RecordT | None,
    *,
    include_archived: bool,
    record_type: str,
    record_id: str,
) -> _RecordT:
    if record is None or (record.status == CareerRecordStatus.ARCHIVED and not include_archived):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{record_type} not found: {record_id}",
        )
    return record
