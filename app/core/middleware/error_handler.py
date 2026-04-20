from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class WorkflowError(Exception):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(WorkflowError)
    async def handle_workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": f"internal_error: {exc}"})
