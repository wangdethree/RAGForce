from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Send a chat message and get a response with citations."""
    ...


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """Send a chat message and get a streaming response (SSE)."""
    ...
