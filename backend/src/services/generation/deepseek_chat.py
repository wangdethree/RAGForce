import time

import httpx

from core.config import settings
from schemas.chat import ChatResponse, Citation


class DeepSeekChat:
    """通过 DeepSeek API 生成对话回复"""

    SYSTEM_PROMPT = """You are RAGForce, an enterprise knowledge base assistant.
Answer questions based solely on the provided context documents.
If the context does not contain enough information to answer, say so clearly.
Always cite the specific documents you used in your answer."""

    async def generate(
        self,
        query: str,
        context_chunks: list[dict],
        history: list[dict] | None = None,
    ) -> ChatResponse:
        start_time = time.time()

        context_text = "\n\n---\n\n".join(
            f"[Source {i+1}] {c['content']}"
            for i, c in enumerate(context_chunks)
        )

        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"Context:\n{context_text}\n\nQuestion: {query}",
        })

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                    json={
                        "model": settings.DEEPSEEK_CHAT_MODEL,
                        "messages": messages,
                        "temperature": 0.3,
                        "max_tokens": 2048,
                    },
                )
                response.raise_for_status()
                data = response.json()
                answer = data["choices"][0]["message"]["content"]
        except Exception as e:
            answer = f"Error calling DeepSeek API: {str(e)}"

        citations = [
            Citation(
                chunk_id=c.get("chunk_id", ""),
                document_name=c.get("document_name", ""),
                content=c["content"][:200],
                score=c.get("score", 0.0),
            )
            for c in context_chunks
        ]

        latency_ms = (time.time() - start_time) * 1000

        return ChatResponse(
            answer=answer,
            citations=citations,
            latency_ms=round(latency_ms, 2),
        )

    async def generate_stream(self, query: str, context_chunks: list[dict], history: list[dict] | None = None):
        context_text = "\n\n---\n\n".join(
            f"[Source {i+1}] {c['content']}"
            for i, c in enumerate(context_chunks)
        )

        messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        if history:
            messages.extend(history)
        messages.append({
            "role": "user",
            "content": f"Context:\n{context_text}\n\nQuestion: {query}",
        })

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                json={
                    "model": settings.DEEPSEEK_CHAT_MODEL,
                    "messages": messages,
                    "temperature": 0.3,
                    "max_tokens": 2048,
                    "stream": True,
                },
            ) as response:
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        yield data


deepseek_chat = DeepSeekChat()
