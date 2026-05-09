import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from schemas.chat import ChatRequest, ChatResponse
from services.retrieval.retriever import retriever
from services.generation.deepseek_chat import deepseek_chat

router = APIRouter()


@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """发送对话消息，返回包含引用的回复"""
    retrieval_result = await retriever.retrieve(
        kb_id=request.kb_id,
        query=request.query,
        top_k=request.top_k,
    )

    context_chunks = [
        {
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "document_name": r.document_name,
            "content": r.content,
            "score": r.score,
        }
        for r in retrieval_result.results
    ]

    return await deepseek_chat.generate(
        query=request.query,
        context_chunks=context_chunks,
        history=request.history,
    )


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """发送对话消息，返回 SSE 流式回复"""
    retrieval_result = await retriever.retrieve(
        kb_id=request.kb_id,
        query=request.query,
        top_k=request.top_k,
    )

    context_chunks = [
        {
            "chunk_id": r.chunk_id,
            "document_id": r.document_id,
            "document_name": r.document_name,
            "content": r.content,
            "score": r.score,
        }
        for r in retrieval_result.results
    ]

    async def event_stream():
        async for chunk_data in deepseek_chat.generate_stream(
            query=request.query,
            context_chunks=context_chunks,
            history=request.history,
        ):
            yield f"data: {chunk_data}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
