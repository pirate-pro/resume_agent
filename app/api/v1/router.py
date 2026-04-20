from fastapi import APIRouter

from app.api.v1 import health, jobs, match_tasks, optimization_tasks, resumes

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(resumes.router, prefix="/resumes", tags=["resumes"])
api_router.include_router(match_tasks.router, prefix="/match-tasks", tags=["match-tasks"])
api_router.include_router(optimization_tasks.router, prefix="/optimization-tasks", tags=["optimization-tasks"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
