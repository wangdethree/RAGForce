class RRFusion:
    """Reciprocal Rank Fusion for combining dense and sparse results."""

    def fuse(
        self,
        dense_results: list[dict],
        sparse_results: list[dict],
        k: int = 60,
    ) -> list[dict]:
        scores: dict[str, dict] = {}

        for rank, result in enumerate(dense_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id not in scores:
                scores[chunk_id] = result.copy()
                scores[chunk_id]["score"] = 0.0
            scores[chunk_id]["score"] += 1.0 / (k + rank)

        for rank, result in enumerate(sparse_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id not in scores:
                scores[chunk_id] = result.copy()
                scores[chunk_id]["score"] = 0.0
            scores[chunk_id]["score"] += 1.0 / (k + rank)

        fused = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
        return fused


rr_fusion = RRFusion()
