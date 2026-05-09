import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from src.services.audit_service import audit_service


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        audit_service.log(
            action=request.method,
            resource_type=request.url.path.split("/")[3] if len(request.url.path.split("/")) > 3 else "unknown",
            resource_id="",
            detail={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
            },
            ip_address=request.client.host if request.client else "",
            duration_ms=duration_ms,
        )
        return response
