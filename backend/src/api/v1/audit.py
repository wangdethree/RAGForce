from fastapi import APIRouter, Query
from sqlalchemy import select, func

from api.deps import DBSession
from models.audit_log import AuditLog
from schemas.audit import AuditLogList, AuditLogResponse

router = APIRouter()


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    action: str | None = Query(None, description="按操作类型筛选"),
    resource_type: str | None = Query(None, description="按资源类型筛选"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: DBSession = None,
):
    """获取审计日志列表，支持按操作类型和资源类型筛选"""
    query = select(AuditLog)

    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)

    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(query)
    logs = result.scalars().all()

    return AuditLogList(items=list(logs), total=total)
