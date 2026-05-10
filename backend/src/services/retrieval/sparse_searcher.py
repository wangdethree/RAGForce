class SparseSearcher:
    """通过 PostgreSQL 全文检索实现 BM25 关键词搜索"""

    async def search(
            self,
            kb_id: str,
            query: str,
            top_k: int = 5,
    ) -> list[dict]:
        return []


sparse_searcher = SparseSearcher()
