from pydantic import BaseModel, Field


class Citation(BaseModel):
    chunk_id: str
    document_name: str
    content: str
    score: float


class ChatRequest(BaseModel):
    kb_id: str
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    history: list[dict] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    latency_ms: float
