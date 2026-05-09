from fastapi import APIRouter
from sqlalchemy import select, func

from src.api.deps import DBSession
from src.models.knowledge_base import KnowledgeBase
from src.models.document import Document, DocumentChunk
from src.models.audit_log import AuditLog
from src.schemas.dashboard import DashboardStats, RecentKB

router = APIRouter()


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(db: DBSession):
    """获取仪表盘统计数据"""
    kb_count = (await db.execute(select(func.count(KnowledgeBase.id)))).scalar() or 0
    doc_count = (await db.execute(select(func.count(Document.id)))).scalar() or 0
    chunk_count = (await db.execute(select(func.count(DocumentChunk.id)))).scalar() or 0
    audit_count = (await db.execute(select(func.count(AuditLog.id)))).scalar() or 0

    return DashboardStats(
        kb_count=kb_count,
        document_count=doc_count,
        chunk_count=chunk_count,
        audit_log_count=audit_count,
    )


@router.get("/recent-kbs", response_model=list[RecentKB])
async def get_recent_kbs(db: DBSession):
    """获取最近创建的知识库"""
    result = await db.execute(
        select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()).limit(5)
    )
    kbs = result.scalars().all()
    return [
        RecentKB(
            id=kb.id,
            name=kb.name,
            document_count=kb.document_count,
            created_at=kb.created_at.isoformat() if kb.created_at else "",
        )
        for kb in kbs
    ]
