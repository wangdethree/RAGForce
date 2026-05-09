from fastapi import APIRouter

from src.api.deps import DBSession
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
    ...


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(body: KnowledgeBaseCreate, db: DBSession):
    """创建新的知识库"""
    ...


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(kb_id: str, db: DBSession):
    """根据 ID 获取知识库详情"""
    ...


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(kb_id: str, body: KnowledgeBaseUpdate, db: DBSession):
    """更新知识库配置"""
    ...


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: str, db: DBSession):
    """删除知识库及其所有文档"""
    ...
