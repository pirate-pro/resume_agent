import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.middleware.request_id import request_id_ctx_var

logger = logging.getLogger("resume_agent.audit")


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            logger.info(
                "audit_event",
                extra={
                    "request_id": request_id_ctx_var.get(),
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                },
            )
        return response
