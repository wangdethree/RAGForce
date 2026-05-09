import httpx

from core.config import settings


class EmbeddingService:
    """通过 BGE-M3 服务生成向量嵌入"""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{settings.EMBEDDING_SERVICE_URL}/embed",
                    json={"texts": texts},
                )
                response.raise_for_status()
                data = response.json()
                return data["embeddings"]
        except Exception:
            return [[0.0] * 1024 for _ in texts]

    async def embed_single(self, text: str) -> list[float]:
        results = await self.embed_batch([text])
        return results[0]


embedding_service = EmbeddingService()
