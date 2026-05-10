"""评测指标纯函数模块。

本模块实现 `design.md` Scope B 的指标计算口径，与学术定义保持一致，便于同行
复核。所有函数 **均为无副作用的纯函数**：不触发 I/O、不依赖全局状态、对相同
输入恒定返回相同输出，可直接被 ``run.py`` 与单元/属性测试复用。

对外暴露四个函数（对应 Requirement 14.1）：

- :func:`recall_at_k`     —— 前 k 条检索结果的召回率
- :func:`mrr_at_k`        —— 前 k 条检索结果的平均倒数排名
- :func:`ndcg_at_k`       —— 前 k 条检索结果的归一化折损累积增益（二值相关性）
- :func:`percentile`      —— 任意序列的第 ``p`` 分位数（简单线性插值）

所有指标函数的返回值均为 ``float``；Recall / MRR / nDCG 的取值域恒在
``[0.0, 1.0]`` 之间，未命中或输入退化时一律返回 ``0.0`` 而非抛异常。
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence, TypeVar

# ``Hit`` 表示单条检索结果的标识符（通常是 chunk_id 或 document_id 字符串，
# 此处放宽为任意可哈希类型，便于测试时直接使用 int 等占位符）。
Hit = TypeVar("Hit")


__all__ = [
    "recall_at_k",
    "mrr_at_k",
    "ndcg_at_k",
    "percentile",
]


def recall_at_k(
    relevant: Iterable[Hit],
    retrieved: Sequence[Hit],
    k: int,
) -> float:
    """计算 Recall@k：前 ``k`` 条命中的相关项数占全部相关项数的比例。

    数学定义（Requirement 14.2）::

        Recall@k = |set(retrieved[:k]) ∩ relevant| / |relevant|

    边界处理：

    - WHEN ``relevant`` 为空集合 → 返回 ``0.0``（避免除零错误）。
    - WHEN ``k <= 0`` 或 ``retrieved`` 为空 → 前 k 条切片为空，命中为 0，
      返回 ``0.0``（`relevant` 非空时）。
    - ``retrieved`` 中的重复元素经 ``set(...)`` 去重后只计一次，符合"位置相关、
      命中不重复计数"的语义。

    :param relevant: 该 query 的 ground-truth 相关项集合（任意可迭代）。
    :param retrieved: 检索系统按排名返回的结果序列（必须支持切片）。
    :param k: 截断位置，通常取 ``5`` 或 ``10``。
    :returns: ``float``，取值恒在 ``[0.0, 1.0]``。
    """

    # 先将相关项标准化为集合，便于 O(1) 成员判断。
    relevant_set = set(relevant)
    if not relevant_set:
        # 空 relevant：按契约直接返回 0.0，而不是抛出 ZeroDivisionError。
        return 0.0

    # 取前 k 条并去重后与 relevant 求交集。
    # 注意：k 若为非正数，Python 切片会返回空列表，后续交集自然为空。
    top_k = set(retrieved[: max(k, 0)])
    hits = top_k & relevant_set

    return len(hits) / len(relevant_set)


def mrr_at_k(
    relevant: Iterable[Hit],
    retrieved: Sequence[Hit],
    k: int,
) -> float:
    """计算 MRR@k：前 ``k`` 条结果中首个命中位置的倒数（按 1-based 计数）。

    数学定义（Requirement 14.3）::

        MRR@k = 1 / rank(第一个命中，1-based)   如果存在命中
              = 0.0                              如果前 k 条全部未命中

    边界处理：

    - WHEN 前 k 条中无任何 relevant 元素 → 返回 ``0.0``。
    - WHEN ``relevant`` 为空集合 → 所有检索结果都不可能命中，返回 ``0.0``。
    - WHEN ``k <= 0`` 或 ``retrieved`` 为空 → 切片为空，返回 ``0.0``。

    :param relevant: 该 query 的 ground-truth 相关项集合。
    :param retrieved: 检索系统按排名返回的结果序列。
    :param k: 截断位置。
    :returns: ``float``，取值恒在 ``[0.0, 1.0]``。
    """

    relevant_set = set(relevant)
    if not relevant_set:
        # 无 ground truth：按契约视为未命中，直接返回 0.0。
        return 0.0

    # 在前 k 条中从左到右寻找首个命中；``enumerate(start=1)`` 直接给出 1-based rank。
    for rank, item in enumerate(retrieved[: max(k, 0)], start=1):
        if item in relevant_set:
            return 1.0 / rank

    # 前 k 条全部未命中 → 0.0。
    return 0.0


def ndcg_at_k(
    relevant: Iterable[Hit],
    retrieved: Sequence[Hit],
    k: int,
) -> float:
    """计算 nDCG@k：二值相关性 + ``log2(i+1)`` 折扣，再用理想 DCG 归一化。

    数学定义（Requirement 14.4），其中 ``i`` 从 1 计数，``rel_i ∈ {0, 1}``::

        DCG@k  = Σ_{i=1..k}  rel_i / log2(i + 1)
        IDCG@k = Σ_{i=1..min(|relevant|, k)}  1 / log2(i + 1)
        nDCG@k = DCG@k / IDCG@k

    边界处理：

    - WHEN ``|relevant ∩ retrieved[:k]| == 0`` → 返回 ``0.0``（分子 DCG 为 0）。
    - WHEN ``relevant`` 为空集合 → 返回 ``0.0``（IDCG 也为 0，约定结果为 0）。
    - WHEN ``k <= 0`` 或 ``retrieved`` 为空 → 切片为空，DCG 为 0，返回 ``0.0``。

    :param relevant: 该 query 的 ground-truth 相关项集合。
    :param retrieved: 检索系统按排名返回的结果序列。
    :param k: 截断位置。
    :returns: ``float``，取值恒在 ``[0.0, 1.0]``。
    """

    relevant_set = set(relevant)
    if not relevant_set:
        # 无 ground truth：IDCG 为 0，按契约返回 0.0。
        return 0.0

    top_k = retrieved[: max(k, 0)]

    # DCG@k：遍历前 k 条，命中贡献 1/log2(i+1)，未命中贡献 0。
    # 使用 enumerate(start=1) 得到 1-based 位置 i，折扣基 ``log2(i + 1)``。
    dcg = 0.0
    for i, item in enumerate(top_k, start=1):
        if item in relevant_set:
            dcg += 1.0 / math.log2(i + 1)

    # 若前 k 条完全未命中，DCG 为 0，按契约直接返回 0.0，避免无意义的除法。
    if dcg == 0.0:
        return 0.0

    # IDCG@k：理想排序下，前 min(|relevant|, k) 个位置都是命中。
    ideal_hits = min(len(relevant_set), max(k, 0))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))

    # IDCG > 0 此分支必然成立（因为 dcg > 0 意味着至少一个命中存在且 k > 0），
    # 但为了防御性再加一次保护。
    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def percentile(values: Sequence[float], p: float) -> float:
    """计算序列的第 ``p`` 分位数，使用简单线性插值（numpy 默认 'linear' 口径）。

    实现细节（Requirement 14.5）：

    1. 空输入直接返回 ``0.0`` —— 用于 latency 列表在极端情况下可能为空的退化处理。
    2. 输入先做升序排序，得到 ``sorted_values``（长度记为 ``n``）。
    3. 以 ``p`` 在 ``[0, 100]`` 区间上的位置映射到数组索引：

           rank = (p / 100) * (n - 1)

       若 ``rank`` 是整数则直接返回 ``sorted_values[rank]``；否则在相邻两个
       元素之间按小数部分做线性插值。

    :param values: 待统计的数值序列，例如 latency_ms 列表。
    :param p: 目标分位数，取值范围建议 ``[0, 100]``（例如 50 表示中位数，
              95 表示 P95）。对越界输入函数不会抛错，但语义无意义，调用方需自检。
    :returns: ``float``，对应第 ``p`` 分位数的插值结果；空输入时为 ``0.0``。
    """

    if not values:
        # 空输入：按契约直接返回 0.0，避免下游报告生成时报错。
        return 0.0

    # 排序复制一份，不污染调用方的原始列表。
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 1:
        # 单元素序列的任何分位数都等于该元素本身。
        return float(sorted_values[0])

    # 将 p 裁剪到 [0, 100]，防御性处理越界输入（不抛错但给出可预期的边界值）。
    p_clamped = min(max(p, 0.0), 100.0)

    # 线性插值：rank 在 [0, n-1] 之间。
    rank = (p_clamped / 100.0) * (n - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        # 正好落在某个整数索引上，直接取值。
        return float(sorted_values[lower])

    # 在相邻两个元素间做线性插值，weight 表示距离下界索引的比例。
    weight = rank - lower
    return float(
        sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight
    )
