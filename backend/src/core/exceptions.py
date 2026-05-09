from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class RAGForceException(Exception):
    def __init__(self, message: str, status_code: int = 500, detail: str | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail


class NotFoundError(RAGForceException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            message=f"{resource} not found: {identifier}",
            status_code=404,
        )


class InvalidOperationError(RAGForceException):
    def __init__(self, message: str):
        super().__init__(message=message, status_code=400)


class IngestionError(RAGForceException):
    def __init__(self, message: str):
        super().__init__(message=message, status_code=422)


def register_exception_handlers(app: FastAPI):
    @app.exception_handler(RAGForceException)
    async def ragforce_exception_handler(request: Request, exc: RAGForceException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )
