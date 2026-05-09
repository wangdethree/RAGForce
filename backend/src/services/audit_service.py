import asyncio
import logging

from core.database import async_session_factory
from models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    """审计日志服务，支持同步日志和异步数据库写入"""

    def log(
        self,
        action: str,
        resource_type: str,
        resource_id: str = "",
        detail: dict | None = None,
        ip_address: str = "",
        duration_ms: int = 0,
    ):
        """同步记录日志（fast path），同时异步写入数据库"""
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

        asyncio.create_task(
            self._persist(
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=detail or {},
                ip_address=ip_address,
                duration_ms=duration_ms,
            )
        )

    async def _persist(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        detail: dict,
        ip_address: str,
        duration_ms: int,
    ):
        """异步写入数据库"""
        try:
            async with async_session_factory() as session:
                log_entry = AuditLog(
                    action=action,
                    resource_type=resource_type,
                    resource_id=resource_id,
                    detail=detail,
                    ip_address=ip_address,
                    duration_ms=duration_ms,
                )
                session.add(log_entry)
                await session.commit()
        except Exception as e:
            logger.warning(f"审计日志写入数据库失败: {e}")


audit_service = AuditService()
