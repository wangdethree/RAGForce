"""内存稀疏检索器（InMemorySparseSearcher）。

本模块为 `services.retrieval.sparse_searcher.SparseSearcher`（基于 PostgreSQL
全文索引的 BM25 关键词检索）提供一个**零 I/O、完全确定性**的测试替身，供
单元 / 集成 / 属性测试以及 eval-lite profile 使用。

实现要点（对应 design.md LLD-4 与 tasks.md 2.3）：

1. **分词规则**：使用 `re.findall(r"[A-Za-z0-9]+|[\\u4e00-\\u9fff]", s.lower())`
   做"CJK 单字 + ASCII 词元"的粗粒度切分，既能覆盖中文语料，也能处理英文
   与数字混排；统一小写化以消除大小写差异。

2. **打分口径**：把 query 与每条 chunk content 的词元各自汇总到
   `collections.Counter`，再对两个 Counter 取交集（`&` 运算符对每个键取
   `min(count_a, count_b)`），将交集所有 value 求和作为重叠分数。只保留
   `score > 0` 的命中，模拟 BM25"命中即候选、未命中则丢弃"的语义。

3. **调用记录**：为满足集成测试 7.1"`use_hybrid=False` 时 sparse_searcher.search
   未被调用"的断言，本 Fake 同时暴露：

   - `calls: list[dict]`：每次 `search` 被调用时追加一条
     `{"kb_id", "query", "top_k"}` 记录（调用日志）
   - `call_count: int`：已调用次数的便捷视图（等于 `len(self.calls)`）

   测试可按需选择粒度，例如 `assert fake_sparse.call_count == 0`。

4. **纯 Python / 零 I/O**：不依赖 PostgreSQL、不启动 async 任务循环之外的
   任何资源；相同输入必产生相同输出，满足可复现性需求（参见 Requirement 18.3）。

对应需求：3.2、6.3、18.3、19.1。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any


# ---------- 模块级分词 / 打分工具（供 FakeRerankerService 等复用） ----------

# 分词正则：先匹配连续的字母/数字序列，再退化为单个 CJK 汉字
# - `[A-Za-z0-9]+`：ASCII 词元（英文单词、数字串），保证"Milvus"、"bge-m3"
#   这类 token 不会被拆散为单字
# - `[\u4e00-\u9fff]`：CJK 统一表意文字单字，避免引入 jieba 等重型依赖
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]")


def _tokenize(s: str) -> Counter:
    """把任意字符串切分为词元并返回 `Counter`。

    使用模块级正则 `_TOKEN_RE`：
    - 英文/数字走 `[A-Za-z0-9]+`，保持词形完整；
    - 中文走单字策略（`[\\u4e00-\\u9fff]`）；
    - 其余字符（标点、空白、全角符号等）不产生词元，被自然丢弃。

    输入在切词前先 `s.lower()`，以消除大小写差异；若 `s` 为空或 `None` 语义的
    落地（空串），返回空 Counter（后续打分会自然得 0）。
    """
    if not s:
        # 空串 / None：返回空 Counter，供后续 `&` 交集直接返回 0
        return Counter()
    # re.findall 保证是列表；Counter 统计每个词元的出现次数
    return Counter(_TOKEN_RE.findall(s.lower()))


def _overlap(a: Counter, b: Counter) -> int:
    """计算两个 Counter 的交集总数，作为词元重叠打分。

    Counter 的 `&` 运算符对共有键取较小计数（multiset intersection），把所有
    value 相加即"共同词元数（含重复）"。取值域 `>= 0`，零表示完全无重叠。
    """
    # `(a & b).values()` 已经自动过滤了零项，sum 返回 int
    return sum((a & b).values())


# ---------- 内存稀疏检索器 ----------


class InMemorySparseSearcher:
    """`SparseSearcher` 的内存版测试替身。

    语义约定
    -------
    - 数据通过 `seed(kb_id, records)` 预置到内存字典；同一个 `kb_id` 可以多次
      seed，记录会累加。
    - `async search(kb_id, query, top_k)` 按词元重叠分数降序返回前 `top_k`
      条；空查询、无命中或未 seed 的 kb 一律返回 `[]`，不抛异常。
    - 每次 `search` 调用都会追加一条日志到 `self.calls`，集成测试可据此断言
      "混合检索关闭时本 Fake 未被调用"（Requirement 3.2）。

    字段
    ----
    store : dict[str, list[dict]]
        `{kb_id: [record, ...]}`，record 至少包含 `chunk_id` 与 `content`，
        也允许携带 `document_id / content_type` 等额外元数据，输出时一并透出。
    calls : list[dict]
        每次 `search` 的调用日志，形如
        `{"kb_id": ..., "query": ..., "top_k": ...}`，按调用顺序追加。
    """

    def __init__(self) -> None:
        # 内存记录表：kb_id → chunk 列表
        self.store: dict[str, list[dict[str, Any]]] = {}
        # 调用日志：集成测试用来断言 sparse 路径是否被触发
        self.calls: list[dict[str, Any]] = []

    # ---- 便捷视图：调用次数 ----
    @property
    def call_count(self) -> int:
        """已触发的 `search` 调用总次数（等于 `len(self.calls)`）。"""
        return len(self.calls)

    # ---- 预置数据 ----
    def seed(self, kb_id: str, records: list[dict[str, Any]]) -> None:
        """向指定 kb 追加一组 chunk 记录。

        参数
        ----
        kb_id : str
            知识库标识；测试中通常用 `"kb-test-001"` 这类稳定字符串。
        records : list[dict]
            每条记录至少包含 `chunk_id`、`content` 两个键；允许携带
            `document_id`、`content_type` 等字段，它们会在 `search` 结果中原样
            透出，便于与生产返回 schema 对齐。
        """
        # 使用 setdefault 保证同一 kb_id 多次 seed 时记录累加而非覆盖
        self.store.setdefault(kb_id, []).extend(records)

    # ---- 检索入口 ----
    async def search(
        self,
        kb_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """按词元重叠打分返回命中 chunk 的前 `top_k` 条。

        流程
        ----
        1. 记录调用日志到 `self.calls`；即便后续走空查询 / 空 kb 的短路分支，
           也算作"被调用过一次"，集成测试据此可严格断言调用契约。
        2. 若 `query` 为空字符串或只含空白字符，则直接返回 `[]`——与
           Retriever 在 `query==""` 时短路的语义一致，避免误产生伪命中。
        3. 若 `kb_id` 未被 seed 过或 seed 列表为空，返回 `[]`。
        4. 否则逐条计算 `_overlap(_tokenize(query), _tokenize(content))`，
           仅保留 `score > 0` 的命中；按分数降序取前 `top_k` 条。

        返回 list[dict]：每条包含原 record 的全部键，再覆盖写入 `score` 字段
        为本次计算出的重叠分数（`float`，与生产返回类型一致）。
        """
        # 1) 记录调用（拷贝入参避免后续被外部修改）
        self.calls.append({"kb_id": kb_id, "query": query, "top_k": top_k})

        # 2) 空查询短路：None、空串、仅空白，统一视为"无检索意图"
        if not query or not query.strip():
            return []

        # 3) 未 seed 或已 seed 但为空：无候选，直接返回
        records = self.store.get(kb_id) or []
        if not records:
            return []

        # 4) 打分：query 词元只分词一次，复用到每条 record
        q_tokens = _tokenize(query)
        if not q_tokens:
            # 查询切词后为空（例如仅含标点），没有可匹配的词元 → 无命中
            return []

        hits: list[dict[str, Any]] = []
        for r in records:
            score = _overlap(q_tokens, _tokenize(r.get("content", "")))
            if score > 0:
                # 透出 record 的全部字段，并用本次分数覆盖 `score` 键
                hits.append({**r, "score": float(score)})

        # 按分数降序；Python 的 sort 稳定，同分项保持 seed 顺序便于测试复现
        hits.sort(key=lambda h: h["score"], reverse=True)

        # 取前 top_k；防御性处理 top_k <= 0 的情形（Retriever 不会这么传，
        # 但属性测试可能生成该边界，返回空列表即可）
        if top_k <= 0:
            return []
        return hits[:top_k]
