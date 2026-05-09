from fastapi import APIRouter

from src.schemas.retrieval import RetrievalRequest, RetrievalResponse

router = APIRouter()


@router.post("", response_model=RetrievalResponse)
async def retrieve(request: RetrievalRequest):
    """检索与查询相关的文档分块"""
    ...
