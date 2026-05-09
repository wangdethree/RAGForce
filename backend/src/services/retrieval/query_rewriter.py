import httpx

from src.core.config import settings


class QueryRewriter:
    """查询改写与扩展，生成多种表述以提升召回率"""

    async def rewrite(self, query: str) -> list[str]:
        """根据原始查询生成多个改写后的查询表述"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.DEEPSEEK_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.DEEPSEEK_API_KEY}"},
                    json={
                        "model": settings.DEEPSEEK_CHAT_MODEL,
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a query reformulation assistant. "
                                    "Given a user query, generate 2-3 alternative formulations "
                                    "that capture the same information need from different angles. "
                                    "Output one query per line, no numbering or prefixes."
                                ),
                            },
                            {"role": "user", "content": query},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 200,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                rewrites = [q.strip() for q in content.strip().split("\n") if q.strip()]
                return [query] + rewrites if rewrites else [query]
        except Exception:
            return [query]


query_rewriter = QueryRewriter()
