import httpx

from src.core.config import settings


class RerankerService:
    """通过 BGE-Reranker-v2-m3 对检索结果重排序"""

    async def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        if not candidates:
            return []

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{settings.RERANKER_SERVICE_URL}/rerank",
                    json={
                        "query": query,
                        "documents": [c["content"] for c in candidates],
                        "top_k": top_k,
                    },
                )
                response.raise_for_status()
                data = response.json()

                reranked = []
                for item in data["results"]:
                    idx = item["index"]
                    candidate = candidates[idx].copy()
                    candidate["score"] = item["score"]
                    reranked.append(candidate)
                return reranked
        except Exception:
            return candidates[:top_k]


reranker_service = RerankerService()
