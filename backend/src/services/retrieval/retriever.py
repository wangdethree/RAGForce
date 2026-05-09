import time

from src.services.retrieval.dense_searcher import dense_searcher
from src.services.retrieval.sparse_searcher import sparse_searcher
from src.services.retrieval.reranker import reranker_service
from src.services.retrieval.fusion import rr_fusion
from src.services.retrieval.query_rewriter import query_rewriter
from src.services.ingestion.embedder import embedding_service
from src.schemas.retrieval import RetrievalResponse, ChunkResult


class Retriever:
    """Orchestrates the Advanced RAG retrieval pipeline."""

    async def retrieve(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
        use_hybrid: bool = True,
        use_rerank: bool = True,
    ) -> RetrievalResponse:
        start_time = time.time()

        # Stage 1: Query rewriting
        queries = await query_rewriter.rewrite(query)

        all_dense_results = []
        all_sparse_results = []

        for q in queries:
            query_embedding = await embedding_service.embed_single(q)
            dense_results = await dense_searcher.search(kb_id, query_embedding, top_k * 2)
            all_dense_results.extend(dense_results)

            if use_hybrid:
                sparse_results = await sparse_searcher.search(kb_id, q, top_k)
                all_sparse_results.extend(sparse_results)

        # Stage 2: Fusion
        if use_hybrid and all_sparse_results:
            candidates = rr_fusion.fuse(all_dense_results, all_sparse_results)
        else:
            seen = set()
            candidates = []
            for r in all_dense_results:
                if r["chunk_id"] not in seen:
                    seen.add(r["chunk_id"])
                    candidates.append(r)

        # Stage 3: Rerank
        if use_rerank:
            candidates = await reranker_service.rerank(query, candidates, top_k)
        else:
            candidates = sorted(candidates, key=lambda x: x["score"], reverse=True)[:top_k]

        # Stage 4: Filter + format
        results = []
        for c in candidates:
            if c["score"] >= similarity_threshold:
                results.append(
                    ChunkResult(
                        chunk_id=c["chunk_id"],
                        document_id=c.get("document_id", ""),
                        document_name="",
                        content=c["content"],
                        score=c["score"],
                        content_type=c.get("content_type", "text"),
                        metadata={},
                    )
                )

        latency_ms = (time.time() - start_time) * 1000

        return RetrievalResponse(
            query=query,
            results=results[:top_k],
            total=len(results),
            latency_ms=round(latency_ms, 2),
        )


retriever = Retriever()
