from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.schemas.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """发送对话消息，返回包含引用的回复"""
    ...


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """发送对话消息，返回 SSE 流式回复"""
    ...
