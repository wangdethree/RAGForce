from pymilvus import Collection, connections, utility

from core.config import settings


class DenseSearcher:
    """通过 Milvus 进行向量相似度搜索"""

    def __init__(self):
        self._connected = False

    def _ensure_connection(self):
        if not self._connected:
            try:
                connections.connect(
                    alias="default",
                    host=settings.MILVUS_HOST,
                    port=settings.MILVUS_PORT,
                )
                self._connected = True
            except Exception:
                pass

    async def search(
        self,
        kb_id: str,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        self._ensure_connection()
        if not self._connected:
            return []

        if not utility.has_collection(settings.MILVUS_COLLECTION_NAME):
            return []

        try:
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
        except Exception:
            return []


dense_searcher = DenseSearcher()
