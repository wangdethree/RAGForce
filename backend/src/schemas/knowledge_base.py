from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(default="")
    top_k: int = Field(default=5, ge=1, le=100)
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    top_k: int | None = Field(None, ge=1, le=100)
    similarity_threshold: float | None = Field(None, ge=0.0, le=1.0)


class KnowledgeBaseResponse(BaseModel):
    id: str
    name: str
    description: str
    top_k: int
    similarity_threshold: float
    document_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseList(BaseModel):
    items: list[KnowledgeBaseResponse]
    total: int
