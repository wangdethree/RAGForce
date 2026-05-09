class SparseSearcher:
    """BM25 keyword search via PostgreSQL full-text search."""

    async def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        return []
