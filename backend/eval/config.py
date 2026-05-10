"""评测运行配置模块（Requirement 13、Requirement 18.4）。

本模块定义评测框架两类核心配置对象，以及一组与 `design.md` LLD-11 对齐的
预置检索配置：

- :class:`RetrievalConfig` —— *不可变* 的单次检索管线开关组合，对应
  ``Retriever.retrieve()`` 的三个布尔标志与一个阈值。``@dataclass(frozen=True)``
  让它可以直接被作为 ``dict`` 的键或 ``set`` 的元素使用，也保证测试/评测
  代码不会在运行过程中意外改写字段。
- :class:`RunConfig` —— 一次 ``python -m eval.run`` 调用的全局参数容器，
  聚合 profile、数据集路径、参与配置、k 值列表、输出目录、随机种子等。

对外暴露（``__all__``）：

- :class:`RetrievalConfig`
- :class:`RunConfig`
- :data:`PRESET_CONFIGS` —— 顺序固定的 4 个预置 ``RetrievalConfig`` 列表
- :data:`PRESET_BY_NAME` —— ``name -> RetrievalConfig`` 的只读映射，便于 CLI
  按名查找
- :func:`validate_config_names` —— 按名字列表解析出对应的 ``RetrievalConfig``，
  未知名字抛 ``ValueError`` 并列出合法值

**不引入生产代码依赖**：本文件只用到 ``dataclasses`` / ``pathlib`` /
``typing`` 标准库，方便在 ``lite`` profile 下脱离 docker-compose 栈直接运行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

__all__ = [
    "RetrievalConfig",
    "RunConfig",
    "PRESET_CONFIGS",
    "PRESET_BY_NAME",
    "validate_config_names",
]


# ---------------------------------------------------------------------------
# RetrievalConfig：单次检索管线的开关组合（Requirement 13.1）
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RetrievalConfig:
    """不可变的检索配置，描述一次 ``retriever.retrieve()`` 的开关组合。

    这些字段将在 runner 中被原样透传给 ``Retriever.retrieve()``，因此语义
    与生产 API 完全一致（见 ``backend/src/services/retrieval/retriever.py``）。

    ``frozen=True`` 让实例成为可哈希、不可变的值对象：
    - 可以作为 ``dict`` 的键（例如以 config 为键聚合指标）；
    - 不会被评测循环中的任何一环意外修改，保证"同一 config 多次运行"的
      可复现性（Requirement 18）。
    """

    # 配置名，如 "dense_only"，在单次运行内必须唯一；仅用于 CLI 选择与
    # 报告中的列标题，不直接进入检索逻辑。
    name: str

    # 是否开启稀疏检索路（PostgreSQL BM25），并与稠密路做 RRF 融合。
    # False 时等价于纯 dense 检索，用于建立 baseline。
    use_hybrid: bool

    # 是否启用 Cross-Encoder 重排。当为 True 时，融合后的候选集会再经过
    # ``reranker_service.rerank`` 一次精排（Requirement 4）。
    use_rerank: bool

    # 是否启用查询改写（query rewriter 把原始 query 扩展为若干变体）。
    # False 时仅用原始 query 走检索，避免 DeepSeek 调用。
    use_query_rewrite: bool

    # 相似度阈值（Requirement 5）。<= 0 表示不过滤；> 0 时只保留
    # ``score >= similarity_threshold`` 的候选。阈值 > 1.0 会导致结果恒空，
    # 属于调用方显式选择，框架不再额外校验。
    similarity_threshold: float = 0.0


# ---------------------------------------------------------------------------
# PRESET_CONFIGS：顺序固定的 4 个预置配置（Requirement 13.1、13.2）
# ---------------------------------------------------------------------------
# 列表顺序同时决定 Markdown 报告中各列的呈现顺序，请勿调换：
#   0) dense_only     —— 纯 dense，baseline
#   1) hybrid         —— dense + sparse + RRF
#   2) hybrid_rerank  —— hybrid 之上再加 rerank
#   3) full           —— hybrid + rerank + query rewrite，对应生产全功能管线
PRESET_CONFIGS: list[RetrievalConfig] = [
    RetrievalConfig(
        name="dense_only",
        use_hybrid=False,
        use_rerank=False,
        use_query_rewrite=False,
        similarity_threshold=0.0,
    ),
    RetrievalConfig(
        name="hybrid",
        use_hybrid=True,
        use_rerank=False,
        use_query_rewrite=False,
        similarity_threshold=0.0,
    ),
    RetrievalConfig(
        name="hybrid_rerank",
        use_hybrid=True,
        use_rerank=True,
        use_query_rewrite=False,
        similarity_threshold=0.0,
    ),
    RetrievalConfig(
        name="full",
        use_hybrid=True,
        use_rerank=True,
        use_query_rewrite=True,
        similarity_threshold=0.0,
    ),
]


# 按名索引的只读映射，便于 CLI 按 ``--configs dense_only,full`` 的方式查找。
# 用 ``Mapping`` 注解强调调用方不应原地修改该字典；若需要扩展请新建一份。
PRESET_BY_NAME: Mapping[str, RetrievalConfig] = {
    cfg.name: cfg for cfg in PRESET_CONFIGS
}


# ---------------------------------------------------------------------------
# RunConfig：一次评测运行的全局参数（Requirement 13.3、16）
# ---------------------------------------------------------------------------
@dataclass
class RunConfig:
    """一次 ``python -m eval.run`` 调用的全局参数容器。

    不使用 ``frozen=True`` 的原因：CLI 解析阶段可能需要在构造后补写
    ``output_dir`` 的绝对化路径、或在某些测试里替换 ``configs`` 子集。
    但字段语义仍然"尽量不可变"—— runner 主流程不应修改已构造的 ``RunConfig``。
    """

    # 执行 profile：取值于 ``{"lite", "full"}``；``lite`` 走内存 Fakes，
    # ``full`` 走真实 docker-compose 栈（Requirement 15）。
    profile: str

    # 评测数据集文件路径，指向 ``backend/eval/datasets/qa_zh.jsonl`` 的
    # JSON Lines 文件（Requirement 11）。
    dataset_path: Path

    # 语料目录路径，指向 ``backend/eval/datasets/corpus/`` 下的 5 篇中文
    # Markdown 文档（Requirement 12）。
    corpus_path: Path

    # 本次运行参与的检索配置列表；由 CLI 从 ``PRESET_CONFIGS`` 中筛选得到。
    # 允许传入 ``PRESET_CONFIGS`` 的任意非空子集。
    configs: list[RetrievalConfig]

    # k 值列表（Requirement 16.4）。对每个 ``k`` 都会分别计算 Recall@k、
    # MRR@k、nDCG@k；默认 ``[5, 10]``。
    k_values: list[int] = field(default_factory=lambda: [5, 10])

    # 测试用 KB 标识。所有语料都写入同一个 KB 中（Requirement 15），
    # 默认取 ``"eval-kb"``。
    kb_id: str = "eval-kb"

    # 报告输出目录；默认写到 ``backend/eval/reports/``，CI 上可通过
    # ``--output-dir`` 覆盖（Requirement 16.5、17.1）。
    output_dir: Path = field(
        default_factory=lambda: Path("backend/eval/reports")
    )

    # 全局随机种子（Requirement 18）。同一 ``seed`` 下 ``lite`` profile 的
    # 两次运行指标必须完全一致。默认 42，并在报告元数据中回显。
    seed: int = 42


# ---------------------------------------------------------------------------
# 校验辅助：按名字解析 RetrievalConfig（Requirement 13.4）
# ---------------------------------------------------------------------------
def validate_config_names(names: list[str]) -> list[RetrievalConfig]:
    """按名字列表从 ``PRESET_BY_NAME`` 解析出 ``RetrievalConfig`` 列表。

    - 保留输入顺序（一般即 CLI 中 ``--configs`` 出现的顺序），便于报告列
      顺序可控。
    - 任一名字未在 ``PRESET_BY_NAME`` 中，抛出 :class:`ValueError` 并在消息
      里附带"未知名字 + 所有合法名字"，对应 CLI 的 exit code 2 路径
      （见 run.py 的参数校验，Requirement 13.4 / 16.8）。

    :param names: 待解析的配置名列表，通常来自 ``--configs`` 命令行参数。
    :returns: 与 ``names`` 长度一致、顺序一致的 ``RetrievalConfig`` 列表。
    :raises ValueError: 任一名字未知时抛出；消息包含未知名字与合法名字列表。
    """

    # 一次性找出全部未知名字，而不是遇到第一个就报错——这样用户只需改一次。
    unknown = [n for n in names if n not in PRESET_BY_NAME]
    if unknown:
        # 合法名字按 PRESET_CONFIGS 的固定顺序展示，保持跟 --help 一致。
        available = ", ".join(cfg.name for cfg in PRESET_CONFIGS)
        raise ValueError(
            f"Unknown retrieval config name(s): {unknown}. "
            f"Available configs: [{available}]."
        )

    # 逐一解析；因为上面已校验全部存在，这里不会触发 KeyError。
    return [PRESET_BY_NAME[n] for n in names]
