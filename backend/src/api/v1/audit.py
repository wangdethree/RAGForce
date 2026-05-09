from fastapi import APIRouter, Query

from src.api.deps import DBSession
from src.schemas.audit import AuditLogList, AuditLogResponse

router = APIRouter()


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    action: str | None = Query(None, description="Filter by action"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DBSession = None,
):
    """获取审计日志列表，支持按操作类型和资源类型筛选"""
    ...
