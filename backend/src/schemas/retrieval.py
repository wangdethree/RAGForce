from pydantic import BaseModel, Field


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    document_name: str
    content: str
    score: float
    content_type: str
    metadata: dict


class RetrievalRequest(BaseModel):
    kb_id: str
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=100)
    similarity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    use_hybrid: bool = Field(default=True, description="Enable hybrid search (dense + sparse)")
    use_rerank: bool = Field(default=True, description="Enable reranking")


class RetrievalResponse(BaseModel):
    query: str
    results: list[ChunkResult]
    total: int
    latency_ms: float
