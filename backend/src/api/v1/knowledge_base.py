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
    """List all knowledge bases."""
    ...


@router.post("", response_model=KnowledgeBaseResponse, status_code=201)
async def create_knowledge_base(body: KnowledgeBaseCreate, db: DBSession):
    """Create a new knowledge base."""
    ...


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
async def get_knowledge_base(kb_id: str, db: DBSession):
    """Get a knowledge base by ID."""
    ...


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
async def update_knowledge_base(kb_id: str, body: KnowledgeBaseUpdate, db: DBSession):
    """Update a knowledge base."""
    ...


@router.delete("/{kb_id}", status_code=204)
async def delete_knowledge_base(kb_id: str, db: DBSession):
    """Delete a knowledge base and all its documents."""
    ...
