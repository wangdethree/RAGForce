"""Fake 重排序服务：FakeRerankerService.

该模块提供生产 :class:`services.retrieval.reranker.RerankerService` 的测试替身,
通过对候选文档与查询文本做"词元重叠"打分来模拟 cross-encoder 重排的相对顺序,
无需真实 BGE-Reranker-v2-m3 HTTP 服务即可在零 Docker 环境中运行。

核心设计约束(满足需求 4.1 / 4.2)：

* **保持候选集不变**：`rerank(query, candidates, top_k)` 的返回列表中每一条的
  ``chunk_id`` **必须**来自输入 ``candidates``；本 Fake 只重打分、不引入任何
  新候选。这是检索管线"召回 vs 重排"职责分离的正确性前提。
* **确定性**：对同一 ``(query, candidates, top_k)`` 两次调用返回语义等价的
  列表(Python 的 ``list.sort`` 是稳定排序,故相同分数的候选保持输入相对顺序)。

实现上复用 :mod:`tests.fakes.sparse_searcher` 中的 ``_tokenize`` / ``_overlap``
两个纯函数,保证 Fake 稀疏检索与 Fake 重排使用一致的分词/打分口径;由于这两
个 Fake 可能按任意顺序被导入,这里采用**函数内惰性导入**,避免模块加载期
出现循环依赖或缺失依赖问题。
"""

from __future__ import annotations


class FakeRerankerService:
    """保持候选集不变、仅按查询与候选内容词元重叠重新打分的 Fake 重排器。

    Duck-typed 接口与生产 :class:`services.retrieval.reranker.RerankerService`
    一致,可直接通过 ``monkeypatch.setattr`` 替换
    ``services.retrieval.retriever.reranker_service`` 单例。
    """

    async def rerank(
        self,
        query: str,
        candidates: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """按词元重叠分数重排候选,严格不引入新候选。

        Args:
            query: 原始查询字符串,用于与每条候选的 ``content`` 做词元重叠。
            candidates: 待重排的候选列表,每个元素为包含 ``chunk_id`` /
                ``content`` 等字段的字典(还可能携带 ``document_id`` /
                ``content_type`` 等元数据,此处整体透传)。
            top_k: 返回的最多条数,不足时原样返回。

        Returns:
            一个长度 ``<= min(len(candidates), top_k)`` 的新列表,其中
            每一项都是对输入某一候选的浅拷贝并覆盖了 ``score`` 字段;
            **返回结果的 ``chunk_id`` 集合一定是输入 ``candidates``
            的 ``chunk_id`` 集合的子集**(需求 4.2)。

        Notes:
            * 空候选直接返回 ``[]``,不抛异常(与生产实现行为一致)。
            * 打分函数来自 :mod:`tests.fakes.sparse_searcher`,采用惰性导入
              以避免模块加载期的顺序依赖。
            * 使用 Python 内置稳定排序,保证同分候选按输入相对顺序排列,
              从而在同一 ``(query, candidates)`` 下输出确定(需求 18.3)。
        """
        # 空候选场景：直接返回空列表,保持与生产 RerankerService 相同的短路行为
        if not candidates:
            return []

        # 惰性导入:避免与 sparse_searcher fake 的模块加载顺序耦合
        # 同时确保 Fake 稀疏检索与 Fake 重排使用同一套分词/打分口径
        from tests.fakes.sparse_searcher import _overlap, _tokenize

        # 对 query 只分词一次,后续对每个候选复用该 Counter
        q_tokens = _tokenize(query)

        # 关键不变式:迭代仅发生在输入 candidates 上,不产生任何新 chunk_id
        # 使用浅拷贝 ``{**c, "score": score}`` 避免修改调用方传入的对象
        rescored: list[dict] = []
        for candidate in candidates:
            # _overlap 返回 Counter 交集的元素总数(int),转 float 以对齐生产返回类型
            score = float(_overlap(q_tokens, _tokenize(candidate.get("content", ""))))
            rescored.append({**candidate, "score": score})

        # 按新分数降序排列;Python 的 sort 是稳定的,因此同分候选保持输入序
        # 这对确定性(需求 18.3)与 RRF 融合后再重排的可追踪性都很重要
        rescored.sort(key=lambda item: item["score"], reverse=True)

        # 截断到 top_k;不足 top_k 时返回全部已重排候选
        return rescored[:top_k]
