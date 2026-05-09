from fastapi import APIRouter
from sqlalchemy import select, func, delete

from src.api.deps import DBSession
from src.core.exceptions import NotFoundError
from src.models.knowledge_base import KnowledgeBase
from src.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseList,
    KnowledgeBaseUpdate,
)

router = APIRouter()


@router.get("", response_model=KnowledgeBaseList)
async def list_knowledge_bases(db: DBSession):
    """获取所有知识库列表"""
    result = await db.execute(select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc()))
    kbs = result.scalars().all()
    total = len(kbs)
    return KnowledgeBaseList(items=list(kbs), total=total)


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(body: KnowledgeBaseCreate, db: DBSession):
    """创建新的知识库"""
    kb = KnowledgeBase(
        name=body.name,
        description=body.description,
        top_k=body.top_k,
        similarity_threshold=body.similarity_threshold,
    )
    db.add(kb)
    await db.flush()
    await db.refresh(kb)
    return kb


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(kb_id: str, db: DBSession):
    """根据 ID 获取知识库详情"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库", kb_id)
    return kb


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(kb_id: str, body: KnowledgeBaseUpdate, db: DBSession):
    """更新知识库配置"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库", kb_id)

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(kb, field, value)

    await db.flush()
    await db.refresh(kb)
    return kb


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: str, db: DBSession):
    """删除知识库及其所有文档"""
    result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("知识库", kb_id)
    await db.delete(kb)
