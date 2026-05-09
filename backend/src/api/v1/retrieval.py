from fastapi import APIRouter

from src.schemas.retrieval import RetrievalRequest, RetrievalResponse
from src.services.retrieval.retriever import retriever

router = APIRouter()


@router.post("", response_model=RetrievalResponse)
async def retrieve(request: RetrievalRequest):
    """检索与查询相关的文档分块"""
    return await retriever.retrieve(
        kb_id=request.kb_id,
        query=request.query,
        top_k=request.top_k,
        similarity_threshold=request.similarity_threshold,
        use_hybrid=request.use_hybrid,
        use_rerank=request.use_rerank,
    )
