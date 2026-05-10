"""FakeEmbeddingService —— 确定性向量化测试替身。

本模块提供 ``FakeEmbeddingService``，用于替换生产环境的
``services.ingestion.embedder.embedding_service`` 单例，使单元测试 / 集成测试 /
API 契约测试 / 评测（lite profile）可以在 **零网络、零 Docker** 的前提下运行。

设计要点（详见 ``design.md`` LLD-4）：

* 维度固定为 **1024**，与生产 BGE-M3 向量维度保持一致，避免下游消费方
  （如 ``InMemoryDenseSearcher``）因维度不一致而报错。
* 基于 **2-char / 3-char shingle（字符级子串词袋）** 提取特征，再用
  **SHA256** 将每个 shingle 哈希到 ``[0, DIM)`` 的桶里累加频次，最后做
  **L2 归一化**。由此两段文本若共享较多子串，其向量也会相关
  （cosine 相似度大致跟随词汇重叠），对检索类测试已经够用。
* 相同输入 **必须** 产生相同输出（可复现性），这是评测 profile 与
  property-based testing 能够确定性通过的基础。
* ``calls`` 调用日志让测试可以断言 embedding 是否被调用
  （例如"空 query 不得触发 embedding 的批量调用"这条需求）。

对应的需求条目：Requirements 18.3（Fakes 确定性）、19.1（通过 monkeypatch
替换生产单例而不修改生产代码）、19.6（只在 dev 依赖范围内新增测试专用库）。
"""

from __future__ import annotations

import hashlib
import math


class FakeEmbeddingService:
    """确定性哈希向量化服务，duck-typed 兼容 ``EmbeddingService``。

    属性：
        dim: 输出向量维度，默认 1024（与生产 BGE-M3 对齐）。
        calls: 调用日志，按调用顺序记录每一次被 embed 过的文本。
            ``embed_batch`` 与 ``embed_single`` 都会追加到这里，便于测试
            断言 embedding 服务被调用的次数和内容。

    契约：
        * ``embed_batch(texts)`` —— 协程，对 ``texts`` 中每条文本独立调用
          ``_vec``，返回 ``list[list[float]]``，长度与入参一致。
        * ``embed_single(text)`` —— 协程，等价于 ``(await embed_batch([text]))[0]``。
        * 对相同的 ``text``，``_vec(text)`` 的输出在进程内外都完全一致
          （依赖 SHA256 的稳定性，不依赖 Python ``hash()`` 的随机化种子）。
    """

    # 向量维度常量：与生产配置 EMBEDDING_DIM=1024 保持一致
    DIM = 1024

    def __init__(self, dim: int = 1024) -> None:
        # 允许少量测试用例以较小维度（如 64）构造实例来提速；默认仍走 1024
        self.dim = dim
        # 调用日志：按顺序收集所有 embed_batch 入参，embed_single 会走 embed_batch 因此也会被记录一次
        self.calls: list[str] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量向量化：记录调用日志并逐条计算特征向量。

        参数:
            texts: 待向量化的文本列表。允许为空列表（返回空列表）。

        返回:
            与 ``texts`` 长度一致的向量列表，每个向量都是长度 ``self.dim``
            的 ``list[float]`` 且已做 L2 归一化。
        """
        # 调用日志优先记录，方便测试断言（例如：空 query 不得触发 embedding 的批量调用）
        self.calls.extend(texts)
        # 对每条文本独立计算向量，保证同输入必得同输出
        return [self._vec(t) for t in texts]

    async def embed_single(self, text: str) -> list[float]:
        """单条向量化：直接复用 ``embed_batch`` 以避免行为漂移。"""
        # 复用 embed_batch 可自动共享 "调用日志记录 + 确定性生成" 逻辑
        results = await self.embed_batch([text])
        return results[0]

    def _vec(self, text: str) -> list[float]:
        """从 ``text`` 派生一条长度为 ``self.dim`` 的 L2 归一化向量。

        步骤：

        1. 枚举 ``text`` 的 2-char 与 3-char 子串（shingle），用 ``set``
           去重，避免长文本的同一 shingle 过度放大某一维度。
        2. 对每个 shingle 求 **SHA256**，取前 8 字节当作大端整数，模
           ``self.dim`` 得到一个桶索引，对该维累加 1.0。
        3. 计算 L2 范数做归一化；若范数为 0（``text == ""``），
           则回退为全零向量（而非除以零），保证不抛异常。

        确定性保证：SHA256 是无状态纯函数，Python 的 ``hash()`` 随机化
        不会影响这里；相同 ``text`` 始终得到相同向量。
        """
        # 1) 构造特征向量的初始零向量（维度固定为 self.dim）
        vec = [0.0] * self.dim

        # 2) 枚举字符级 2-gram 与 3-gram 并去重（set 避免频次爆炸）
        #    range 使用 max(0, ...) 避免 text 长度小于 n 时出现负数上界
        shingles: set[str] = set()
        for n in (2, 3):
            for i in range(max(0, len(text) - n + 1)):
                shingles.add(text[i : i + n])

        # 3) 逐个 shingle 哈希到桶并累加
        for s in shingles:
            # SHA256 摘要的前 8 字节解释为大端整数，保证跨平台一致
            digest = hashlib.sha256(s.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self.dim
            vec[bucket] += 1.0

        # 4) L2 归一化；零向量保护 —— 空文本 / 无法提取任何 shingle 时直接返回零向量
        norm_sq = sum(x * x for x in vec)
        if norm_sq == 0.0:
            # 空文本或 shingles 为空（例如长度 <2 的文本）时，返回纯零向量
            # 下游 InMemoryDenseSearcher 的 _cosine 对零向量做了同样的保护，不会抛除零异常
            return vec
        norm = math.sqrt(norm_sq)
        return [x / norm for x in vec]
