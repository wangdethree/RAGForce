from pymilvus import Collection

from src.core.config import settings


class DenseSearcher:
    """Vector similarity search via Milvus."""

    async def search(
        self,
        kb_id: str,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        collection = Collection(name=settings.MILVUS_COLLECTION_NAME)

        search_params = {"metric_type": "IP", "params": {"nprobe": 16}}
        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=f'kb_id == "{kb_id}"',
            output_fields=["id", "document_id", "content", "content_type", "chunk_index"],
        )

        hits = []
        for hit in results[0]:
            hits.append({
                "chunk_id": hit.id,
                "document_id": hit.entity.get("document_id", ""),
                "content": hit.entity.get("content", ""),
                "content_type": hit.entity.get("content_type", "text"),
                "score": float(hit.distance),
            })

        return hits


dense_searcher = DenseSearcher()
