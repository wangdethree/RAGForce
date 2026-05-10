"""内存版稠密检索 Fake —— `InMemoryDenseSearcher`

该模块实现测试/评测（lite profile）场景下用于替换生产
`services.retrieval.dense_searcher.dense_searcher` 单例的 Fake。它在纯内存中
维护 ``{kb_id: [chunk_record]}`` 结构，并以 cosine 相似度对查询向量与已预置的
chunk 向量打分，返回 top_k 命中结果。

设计要点：

- **接口形状保持与生产一致**：对外暴露 ``async def search(kb_id, query_embedding, top_k)``，
  返回元素字段为 ``chunk_id / document_id / content / content_type / score``
  的 ``list[dict]``，便于通过 ``monkeypatch.setattr`` 无痛替换生产单例。
- **确定性**：对同样的 ``(kb_id, query_embedding, top_k)`` 输入，只要 ``seed`` 的
  记录未变，返回结果就完全一致（满足评测可复现性要求）。
- **优雅退化**：空 kb、不存在的 kb、零向量查询、零向量 chunk 等极端输入一律返回
  ``[]``，**禁止抛异常**；由上游检索管线决定如何处理空结果。

Validates: Requirements 6.1、6.2、18.3、19.1
"""

from __future__ import annotations

import math
from typing import Any


class InMemoryDenseSearcher:
    """基于内存字典的稠密检索 Fake，使用 cosine 相似度打分。

    存储结构（``self.store``）：

    ``{
        kb_id: [
            {
                "chunk_id": str,        # chunk 主键
                "document_id": str,     # 所属文档 id
                "content": str,         # chunk 原文
                "content_type": str,    # 默认 "text"
                "embedding": list[float],  # 与 query 同维的向量
            },
            ...
        ]
    }``

    该结构不做索引，检索时采用线性扫描 + 排序；对于测试/评测 lite profile 的规模
    （最多几百条 chunk），性能完全够用且保持实现足够简单。
    """

    def __init__(self) -> None:
        # 每个 kb_id 映射到一组 chunk 记录；使用普通字典即可，无需加锁
        # （测试场景下为单线程协程）。
        self.store: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------
    # 预置数据
    # ------------------------------------------------------------------
    def seed(self, kb_id: str, records: list[dict[str, Any]]) -> None:
        """向指定知识库追加预置记录。

        参数
        ----
        kb_id:
            知识库标识；若尚未存在则自动初始化为空列表。
        records:
            一组 chunk 记录，每条至少需包含 ``chunk_id`` / ``content`` /
            ``embedding`` 字段；``document_id`` / ``content_type`` 缺省时由
            ``search`` 时以默认值回填。

        说明：为保持简单，本方法**不做去重**——重复调用会追加，测试如需重置
        应自行重建 ``InMemoryDenseSearcher`` 实例或清空 ``self.store``。
        """

        # setdefault 保证 kb_id 对应条目存在后再 extend
        self.store.setdefault(kb_id, []).extend(records)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    async def search(
        self,
        kb_id: str,
        query_embedding: list[float],
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """按 cosine 相似度返回 top_k 命中。

        行为契约：

        - 当 ``kb_id`` 不存在或对应列表为空时，直接返回 ``[]``。
        - 当 ``top_k <= 0`` 时，返回 ``[]``（与"无召回"语义一致）。
        - 当 ``query_embedding`` 为空列表或全零向量时，返回 ``[]``；这是 Fake
          层对"零向量"退化输入的优雅处理。
        - 任何 chunk 的 ``embedding`` 为空或全零时，跳过该条，不参与排序。

        返回字段固定为：
        ``chunk_id / document_id / content / content_type / score``，
        其中 ``score`` 为 cosine 相似度（``[-1, 1]``，实际测试中因向量经过 L2
        归一化，通常落在 ``[0, 1]``）。
        """

        # 不存在或空 kb → 直接返回空列表，保持对"空知识库"退化输入的优雅处理
        records = self.store.get(kb_id)
        if not records:
            return []

        # top_k 非正数视为"不要任何结果"，避免下游出现负切片等异常
        if top_k <= 0:
            return []

        # 预计算 query 向量的范数；若为零向量则整体返回 []（零向量无法定义方向）
        query_norm = _l2_norm(query_embedding)
        if query_norm == 0.0:
            return []

        hits: list[dict[str, Any]] = []
        for record in records:
            embedding = record.get("embedding") or []
            doc_norm = _l2_norm(embedding)
            # chunk 向量为空或零向量时跳过，避免产生 NaN 分数污染排序
            if doc_norm == 0.0:
                continue

            # cosine 相似度 = (a · b) / (|a| * |b|)
            dot = _dot(query_embedding, embedding)
            score = dot / (query_norm * doc_norm)

            hits.append(
                {
                    "chunk_id": record["chunk_id"],
                    "document_id": record.get("document_id", ""),
                    "content": record.get("content", ""),
                    "content_type": record.get("content_type", "text"),
                    "score": float(score),
                }
            )

        # 按分数降序排序并截取 top_k；`sorted` 为稳定排序，保证在分数并列时
        # 保持 seed 的原始顺序，满足可复现性（Requirement 18.3/18.4）。
        hits.sort(key=lambda h: h["score"], reverse=True)
        return hits[:top_k]


# ----------------------------------------------------------------------
# 内部工具函数（模块私有）
# ----------------------------------------------------------------------
def _dot(a: list[float], b: list[float]) -> float:
    """计算两个向量的点积；长度不一致时按较短者截断（不报错，便于 Fake 容错）。"""

    # 使用 zip 自然按较短序列长度迭代，等价于显式截断
    return sum(x * y for x, y in zip(a, b))


def _l2_norm(vec: list[float]) -> float:
    """计算 L2 范数；空向量或零向量返回 ``0.0``。

    注意：返回 ``0.0`` 而非 ``1.0``——调用方需自行判断零向量并短路，以避免误将
    不可比较的零向量当作普通方向参与打分。
    """

    if not vec:
        return 0.0
    return math.sqrt(sum(x * x for x in vec))
