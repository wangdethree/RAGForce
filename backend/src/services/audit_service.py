import logging

logger = logging.getLogger(__name__)


class AuditService:
    def log(
        self,
        action: str,
        resource_type: str,
        resource_id: str = "",
        detail: dict | None = None,
        ip_address: str = "",
        duration_ms: int = 0,
    ):
        logger.info(
            "AUDIT",
            extra={
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "detail": detail or {},
                "ip_address": ip_address,
                "duration_ms": duration_ms,
            },
        )


audit_service = AuditService()
