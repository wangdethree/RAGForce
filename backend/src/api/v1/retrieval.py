from fastapi import APIRouter

from src.schemas.retrieval import RetrievalRequest, RetrievalResponse

router = APIRouter()


@router.post("", response_model=RetrievalResponse)
async def retrieve(request: RetrievalRequest):
    """Retrieve relevant document chunks for a query."""
    ...
