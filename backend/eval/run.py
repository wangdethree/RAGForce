"""评测 CLI 入口 —— `python -m eval.run`（对应 Requirement 16 与子任务 13.6）。

本模块提供 **两个入口**：

1. :func:`main`      —— 同步 CLI 入口，内部 ``asyncio.run`` 驱动 :func:`run_eval`，
   返回 Unix 风格 exit code（``0`` 成功、``2`` 参数/数据集错误、``3`` 运行期错误）。
   典型调用：``python -m eval.run --profile lite --configs dense_only --k 5``。
2. :func:`run_eval`  —— **异步程序化入口**，接受一个 :class:`RunConfig` 并返回
   聚合指标字典，供 `tests/integration/test_eval_smoke.py`（14.1）与属性测试
   （14.2）直接 ``await`` 调用，避免通过 subprocess 拉起进程带来的开销与
   调试不便。

编排流程（与 ``design.md`` LLD-15 / Requirement 16 保持一致）：

- 参数解析 → 固定随机种子 → 装配 profile 适配器 → （full 独有）健康探活 →
  ``ingest_corpus`` 将 corpus 装入 dense/sparse → ``load_and_validate`` 读取
  QA 数据集 → （full 独有）warmup 查询规避冷启动 → 双层循环 ``config × k``
  执行 ``retriever.retrieve`` → 按 query 收集 recall/mrr/ndcg/latency → 用
  ``metrics.percentile`` 得到 p50/p95 → 调 ``eval.report.render``
  （若模块未实现则优雅降级为 stderr warning）→ 返回聚合指标字典。

异常 → exit code 映射（Requirement 16.8 / 16.9）：

- :class:`ValueError`（未知 config、``--k`` 非正整数）、
  :class:`DatasetValidationError`、:class:`FileNotFoundError`
  （dataset/corpus 缺失） → exit ``2``
- profile ``health_check`` 返回非空、``retriever.retrieve`` 运行期抛异常
  → exit ``3``
- 正常完成 → exit ``0``
- ``KeyboardInterrupt`` → 不捕获，让 Python 默认行为（exit 130）生效

所有路径统一使用 :class:`pathlib.Path`（Requirement 20.5）；Windows 入口处
显式设置 ``WindowsSelectorEventLoopPolicy``（Requirement 20.2）。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import random
import sys
import time
from pathlib import Path
from typing import Any

# ``eval.*`` 子模块：配置、数据集、入库、指标 —— 均为零生产依赖的纯模块。
# 生产的 ``retriever`` 单例在主循环内按需 import，避免在 CLI 启动期就把
# 生产检索路径的所有依赖（pymilvus、httpx 等）拉起。
from eval.config import (
    RunConfig,
    validate_config_names,
)
from eval.dataset import DatasetValidationError, load_and_validate
from eval.ingest import ingest_corpus
from eval.metrics import mrr_at_k, ndcg_at_k, percentile, recall_at_k

__all__ = ["main", "run_eval"]


# ---------------------------------------------------------------------------
# 默认路径：相对 **backend/** 工作目录。CLI 调用方推荐从 ``backend/`` 启动。
# ---------------------------------------------------------------------------
# 评测数据集 / 语料 / 报告三处默认路径：
# - 对应 Requirement 16.5：未指定 ``--output-dir`` 时报告写入 ``backend/eval/reports/``
# - 对应 Requirement 11.1 / 12.1：数据集与语料的标准位置
_DEFAULT_DATASET = Path("backend/eval/datasets/qa_zh.jsonl")
_DEFAULT_CORPUS = Path("backend/eval/datasets/corpus")
_DEFAULT_OUTPUT_DIR = Path("backend/eval/reports")

# 默认参与配置：4 个预置配置全部跑一遍，与 ``PRESET_CONFIGS`` 顺序一致。
_DEFAULT_CONFIGS = "dense_only,hybrid,hybrid_rerank,full"

# 默认 k 值列表：按 Requirement 16.4 取 ``[5, 10]``，以逗号分隔的字符串存储，
# 便于 argparse 直接透传到 ``_parse_args`` 的解析逻辑。
_DEFAULT_K = "5,10"


# ---------------------------------------------------------------------------
# 自定义异常：只在 ``main`` 内部使用，不对外暴露
# ---------------------------------------------------------------------------
class _HealthCheckError(RuntimeError):
    """full profile 健康探活失败的内部标志异常。

    仅用于把 exit code 3 路径与其他运行期错误区分开：``health_check`` 返回
    非空列表时抛出；由 :func:`main` 捕获后直接返回 3，stderr 已在抛出前打印。
    """

    def __init__(self, down: list[str]) -> None:
        super().__init__(f"health_check failed: {down!r}")
        # 把未连通依赖列表原样挂在属性上，方便测试断言
        self.down = list(down)


# ---------------------------------------------------------------------------
# argparse：参数定义与解析（Requirement 16.1 / 16.2）
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    """构造 argparse 解析器 —— 所有参数与默认值均集中在此，方便测试断言。"""

    # prog="eval" 让 ``python -m eval.run --help`` 的用法行显示 ``usage: eval ...``
    # 而不是 ``usage: run.py ...``，与 Requirement 16.1 描述的入口名一致。
    parser = argparse.ArgumentParser(
        prog="eval",
        description="RAGForce 检索质量离线评测 runner（lite / full 两种 profile）",
    )

    # --profile：执行 profile，决定适配器是 Fake 还是生产单例（Requirement 15）
    parser.add_argument(
        "--profile",
        choices=["lite", "full"],
        default="lite",
        help="执行 profile：lite(默认, 零 Docker) 或 full(真实 docker-compose 栈)",
    )

    # --configs：参与本次评测的检索配置名，逗号分隔；未指定则跑全部 4 个预置
    parser.add_argument(
        "--configs",
        default=_DEFAULT_CONFIGS,
        help=(
            "检索配置名，逗号分隔。可选：dense_only, hybrid, hybrid_rerank, full。"
            "默认：'dense_only,hybrid,hybrid_rerank,full'"
        ),
    )

    # --k：截断位置列表，逗号分隔正整数；默认 5,10 对应 Requirement 16.4
    parser.add_argument(
        "--k",
        default=_DEFAULT_K,
        help="k 值列表，逗号分隔的正整数。默认：'5,10'",
    )

    # --dataset：QA JSONL 路径，默认 backend/eval/datasets/qa_zh.jsonl
    parser.add_argument(
        "--dataset",
        type=Path,
        default=_DEFAULT_DATASET,
        help="QA 数据集 JSONL 路径。默认：backend/eval/datasets/qa_zh.jsonl",
    )

    # --corpus：corpus 目录（存放 *.md），默认 backend/eval/datasets/corpus
    parser.add_argument(
        "--corpus",
        type=Path,
        default=_DEFAULT_CORPUS,
        help="语料目录路径，内含 *.md。默认：backend/eval/datasets/corpus",
    )

    # --kb-id：评测写入的 KB 标识；所有 corpus 都写到同一个 KB（Requirement 15）
    parser.add_argument(
        "--kb-id",
        default="eval-kb",
        help="评测 KB 标识。默认：eval-kb",
    )

    # --output-dir：报告输出目录；Requirement 16.5 默认 backend/eval/reports/
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="Markdown 报告输出目录。默认：backend/eval/reports",
    )

    # --seed：全局随机种子；Requirement 18.1 / 18.5 默认 42
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="全局随机种子。默认：42",
    )

    return parser


def _parse_args(argv: list[str] | None) -> RunConfig:
    """把命令行参数解析为 :class:`RunConfig`。

    参数校验策略：

    - 未知 ``--configs`` 名字 → 由 :func:`validate_config_names` 抛
      :class:`ValueError`，``main`` 捕获后映射为 exit ``2``；
    - ``--k`` 非正整数或为空 → 抛 :class:`ValueError`，同样映射为 exit ``2``；
    - argparse 内建错误（未知参数、类型不匹配）→ argparse 自己 ``sys.exit(2)``，
      与 Requirement 16.8 的退出码一致，所以不必额外处理。
    """

    parser = _build_parser()
    # parse_args 失败时 argparse 会打印 usage 并 sys.exit(2)；--help 时 sys.exit(0)。
    # 这两种退出码本身就符合 Requirement 16.6 / 16.8，无需拦截。
    ns = parser.parse_args(argv)

    # ---- 解析 --configs：逗号分隔，strip 后保留顺序 ----
    # 保留用户指定的顺序，便于报告列顺序可控。
    config_names = [n.strip() for n in str(ns.configs).split(",") if n.strip()]
    if not config_names:
        raise ValueError("--configs must be a non-empty, comma-separated list")
    # validate_config_names 对未知名字会抛 ValueError 并列出合法选项
    configs = validate_config_names(config_names)

    # ---- 解析 --k：逗号分隔正整数 ----
    raw_k_parts = [x.strip() for x in str(ns.k).split(",") if x.strip()]
    if not raw_k_parts:
        raise ValueError("--k must be a non-empty, comma-separated list of positive integers")
    k_values: list[int] = []
    for part in raw_k_parts:
        try:
            k_int = int(part)
        except ValueError as exc:
            raise ValueError(
                f"--k contains non-integer value: {part!r} (must be positive integer)"
            ) from exc
        if k_int <= 0:
            raise ValueError(
                f"--k must be positive integers, got: {k_int} (non-positive not allowed)"
            )
        k_values.append(k_int)

    # 构造 RunConfig（冻结式的组合入参：方便在测试中复用、可以原样传给 run_eval）
    return RunConfig(
        profile=ns.profile,
        dataset_path=Path(ns.dataset),
        corpus_path=Path(ns.corpus),
        configs=configs,
        k_values=k_values,
        kb_id=ns.kb_id,
        output_dir=Path(ns.output_dir),
        seed=ns.seed,
    )


# ---------------------------------------------------------------------------
# 程序化入口：run_eval
# ---------------------------------------------------------------------------
async def run_eval(run_config: RunConfig) -> dict[str, Any]:
    """程序化评测入口 —— 供测试直接 ``await`` 调用，不经过 subprocess。

    参数
    ----
    run_config:
        由 :func:`_parse_args` 或测试构造的评测运行配置。

    返回
    ----
    ``dict``，包含以下键：

    - ``report_path`` (``Path | None``)：Markdown 报告路径；``eval.report``
      尚未实现时为 ``None`` 且 stderr 已打印降级 warning。
    - ``wall_time_s`` (``float``)：从 ``run_eval`` 开始到 metrics 聚合结束
      的墙钟耗时（秒）。
    - ``metrics`` (``dict[tuple[str, int], dict[str, float]]``)：以
      ``(config_name, k)`` 为键，值含 ``recall / mrr / ndcg / p50_ms / p95_ms``
      5 个浮点字段。
    - ``per_query`` (``list[dict]``)：按 ``(config, k, query)`` 展开的每条
      QA 的命中情况，字段 ``qid / config_name / k / hit``。

    异常传播
    --------
    - :class:`FileNotFoundError` / :class:`DatasetValidationError`
      → 由 ``load_and_validate`` 抛出，上层 ``main`` 映射为 exit ``2``。
    - :class:`ValueError` → 来自 ``_parse_args``，不会在本函数中再次抛出。
    - :class:`_HealthCheckError` → ``full`` profile 的 ``health_check`` 返回
      非空列表时抛出；``main`` 映射为 exit ``3``。
    - 其余 :class:`Exception`（例如 Milvus 超时、embedding HTTP 非 2xx）
      → 原样外抛，``main`` 映射为 exit ``3``。
    """

    # 墙钟计时从 run_eval 入口开始：含 ingest、warmup、主循环与 metrics 聚合，
    # 但不含 report.render（报告里单独显示）。
    wall_start = time.time()

    # ---- 1) 固定随机种子（Requirement 18.1）------------------------------
    # Python 内置 random：影响 hashmap / 集合遍历之外的大多数随机来源。
    random.seed(run_config.seed)
    # numpy（可选）：在有科学计算栈时保证更广的随机源一致性。
    try:
        import numpy as np  # type: ignore[import-not-found]

        np.random.seed(run_config.seed)
    except ImportError:
        # numpy 不是本项目的强依赖，缺失时静默跳过即可。
        pass

    # ---- 2) 装配 profile 适配器（Requirement 15.1 / 15.3 / 19.3）--------
    # importlib 允许把 profile 名作为动态字符串拼接；相比 ``if/else`` 更方便
    # 未来扩展（例如新增 full_chat profile）。
    profile_module = importlib.import_module(f"eval.profiles.{run_config.profile}")
    # build_adapters 返回 5 键字典：embedding / dense / sparse / reranker / query_rewriter
    adapters = profile_module.build_adapters()
    # install 对 lite 会向生产 retriever 模块做属性注入；对 full 为空操作。
    profile_module.install(adapters)

    # ---- 3) full profile 专属：依赖健康探活（Requirement 15.5）----------
    # health_check 为 async 函数，返回未连通依赖名称列表；空列表 = 全健康。
    # 仅当 profile 模块显式提供该函数时才调用（lite 不提供）。
    if hasattr(profile_module, "health_check"):
        down = await profile_module.health_check(adapters)
        if down:
            # 先打 stderr，再抛内部异常；main 捕获后直接 return 3。
            print(
                f"ERROR: health check failed, unreachable dependencies: {down}",
                file=sys.stderr,
            )
            raise _HealthCheckError(down)

    # ---- 4) 语料入库：doc_map 供 ground truth 展开（Requirement 11.6）---
    # ingest_corpus 内部按文件名排序与 chunk index 升序迭代，保证稳定。
    doc_map = await ingest_corpus(
        run_config.corpus_path,
        run_config.kb_id,
        embedder=adapters["embedding"],
        dense_store=adapters["dense"],
        sparse_store=adapters["sparse"],
    )

    # ---- 5) 加载并校验 QA 数据集（Requirement 11.2 / 11.4）--------------
    # load_and_validate 会在任一条违约时抛 DatasetValidationError；
    # 文件不存在时抛 FileNotFoundError；均由 main 映射为 exit 2。
    entries = load_and_validate(run_config.dataset_path, run_config.corpus_path)

    # ---- 6) full profile 专属：warmup 查询（Requirement 15.6）-----------
    # 评测的 p50/p95 只统计主循环中的真实查询，warmup 不计入。
    # 只有 entries 非空才做；warmup 失败也会外抛，main 映射为 exit 3。
    if run_config.profile == "full" and entries:
        # 惰性 import 生产 retriever 单例：避免 lite 路径下拉起生产链路
        # （虽然生产 retriever 的大部分 I/O 在首次 retrieve 时才发生，
        #  但 import 本身也会触发 pymilvus 等客户端类的加载）。
        from services.retrieval.retriever import retriever as _retriever

        # 使用 entries[0] 的 query 做 warmup；top_k=5 足以触发所有检索路径
        await _retriever.retrieve(
            kb_id=run_config.kb_id,
            query=entries[0].query,
            top_k=5,
            similarity_threshold=0.0,
            use_hybrid=True,
            use_rerank=False,
        )

    # ---- 7) 主循环：config × k × query，收集指标 -------------------------
    # 再次惰性 import：无论 lite 还是 full，到此 profile 已完成装配，
    # 导入 retriever 时读取到的 dense_searcher 等名字都是正确的（lite 已 patch）。
    from services.retrieval.retriever import retriever

    # per_query：按 (qid, config_name, k) 展开的每条 QA 命中情况；
    # 供 Markdown 报告 Per-query breakdown 段使用（Requirement 17.4）。
    per_query: list[dict[str, Any]] = []

    # metrics：以 (config_name, k) 为键的聚合指标字典。使用 tuple 作为键
    # 保留可排序性（sorted(metrics) 按 config 名与 k 升序）。
    metrics: dict[tuple[str, int], dict[str, float]] = {}

    # 外层遍历每个检索配置；配置顺序保持 run_config.configs 的原顺序（CLI 顺序）。
    for cfg in run_config.configs:
        # 内层再遍历每个 k 值。先跑完一个 (cfg, k) 再进下一个，便于逐组聚合。
        for k in run_config.k_values:
            recall_scores: list[float] = []
            mrr_scores: list[float] = []
            ndcg_scores: list[float] = []
            latencies: list[float] = []

            # 按 entries 原顺序遍历 QA；load_and_validate 保证了该顺序就是
            # 文件顺序（Requirement 18.4 的稳定迭代前提）。
            for qe in entries:
                # ---- 构造 ground truth 集合 ----
                # 优先使用 QA 记录自带的 relevant_chunk_ids；否则按
                # Requirement 11.6 回退到按 document_id 展开 chunk_ids。
                if qe.relevant_chunk_ids is not None:
                    relevant: set[str] = set(qe.relevant_chunk_ids)
                else:
                    relevant = set()
                    for doc_id in qe.relevant_doc_ids:
                        # doc_map.get 容忍缺失（理论上 load_and_validate 已校验），
                        # 缺失时贡献空集合，不影响后续交集运算。
                        relevant.update(doc_map.get(doc_id, []))

                # ---- 调用生产 retriever.retrieve ----
                # 注意：生产 Retriever.retrieve 的签名只接受 use_hybrid /
                # use_rerank / similarity_threshold 三个开关，不直接暴露
                # use_query_rewrite。是否启用查询改写由 lite/full profile
                # 在装配阶段通过注入不同 query_rewriter 实例来控制；因此这里
                # 仅透传与生产签名对齐的 5 个参数（Requirement 13.5 补注）。
                resp = await retriever.retrieve(
                    kb_id=run_config.kb_id,
                    query=qe.query,
                    top_k=k,
                    similarity_threshold=cfg.similarity_threshold,
                    use_hybrid=cfg.use_hybrid,
                    use_rerank=cfg.use_rerank,
                )

                # 仅取 chunk_id 列表，顺序 = 检索系统返回的排名
                retrieved_ids = [r.chunk_id for r in resp.results]

                # ---- 计算三类指标 ----
                r_val = recall_at_k(relevant, retrieved_ids, k)
                m_val = mrr_at_k(relevant, retrieved_ids, k)
                n_val = ndcg_at_k(relevant, retrieved_ids, k)

                recall_scores.append(r_val)
                mrr_scores.append(m_val)
                ndcg_scores.append(n_val)
                # latency_ms 来自 RetrievalResponse.latency_ms；单位已经是毫秒
                latencies.append(float(resp.latency_ms))

                # ---- 记录 per-query 命中情况 ----
                # hit 采用"前 k 条中存在任一相关 chunk_id"的布尔判定。
                hit = any(rid in relevant for rid in retrieved_ids[:k])
                per_query.append(
                    {
                        "qid": qe.qid,
                        # 携带 query 文本以便 report.py 渲染"逐条命中"表的
                        # query 前 40 字列（见 13.7 报告结构）。
                        "query": qe.query,
                        "config_name": cfg.name,
                        "k": k,
                        "hit": hit,
                    }
                )

            # ---- 聚合当前 (cfg, k) 的平均指标 + 延迟百分位 ----
            # 空 entries 退化保护：除数为 0 时直接返回 0.0，不抛异常。
            n_queries = len(recall_scores)
            metrics[(cfg.name, k)] = {
                "recall": sum(recall_scores) / n_queries if n_queries else 0.0,
                "mrr": sum(mrr_scores) / n_queries if n_queries else 0.0,
                "ndcg": sum(ndcg_scores) / n_queries if n_queries else 0.0,
                # percentile 对空列表已做保护，返回 0.0
                "p50_ms": percentile(latencies, 50),
                "p95_ms": percentile(latencies, 95),
            }

    # 墙钟时间到 metrics 聚合结束为止；report.render 的耗时不计入 wall_time_s
    wall_time_s = time.time() - wall_start

    # ---- 8) 生成 Markdown 报告（优雅降级）------------------------------
    # eval.report 是 Task 13.7 的产物；13.6 在前、13.7 在后，因此本函数
    # 必须容忍 report 模块缺失的情况。通过捕获 ImportError 判定是否落地。
    report_path: Path | None = None
    try:
        # 仅在真正需要时才导入；缺失时 ImportError 会被下方捕获。
        from eval import report as report_module  # type: ignore[import-not-found]
        from datetime import datetime as _datetime  # 局部 import：仅报告段使用

        # report.render 的签名约定（由 13.7 落地）：接收 run_config、
        # entries_count、metrics、per_query、wall_time_s、started_at，
        # 返回写出的 Markdown 文件路径。
        report_path = report_module.render(
            run_config=run_config,
            entries_count=len(entries),
            metrics=metrics,
            per_query=per_query,
            wall_time_s=wall_time_s,
            started_at=_datetime.now(),
        )
    except ImportError:
        # eval.report 尚未实现：打印一次 warning 到 stderr，继续返回指标。
        print(
            "WARNING: eval.report module is not available; "
            "skipping Markdown report generation.",
            file=sys.stderr,
        )

    # ---- 9) 返回聚合结果字典 -------------------------------------------
    # 键的顺序：report_path / wall_time_s / metrics / per_query，与本函数
    # docstring 一致，便于测试直接解包断言。
    return {
        "report_path": report_path,
        "wall_time_s": wall_time_s,
        "metrics": metrics,
        "per_query": per_query,
    }


# ---------------------------------------------------------------------------
# CLI 入口：main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数、执行评测、把异常映射为 Unix 退出码。

    :param argv: 命令行参数列表；``None`` 时从 ``sys.argv[1:]`` 读取。
    :returns: Unix 风格 exit code：``0``/``2``/``3``（定义见模块 docstring）。
    """

    # ---- Windows 事件循环策略（Requirement 20.2）------------------------
    # Windows 默认的 ProactorEventLoop 在 asyncio + httpx + aiosqlite 路径上
    # 会出现兼容性问题，这里强制切换为 Selector。注意：必须在 ``asyncio.run``
    # 之前设置，因此放在 main 的最前。
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # ---- 参数解析 -------------------------------------------------------
    # argparse 的 parse_args 在 --help 时 sys.exit(0)、在参数错误时 sys.exit(2)；
    # 这两种退出码本身符合 Requirement 16.6 / 16.8，故不额外拦截 SystemExit。
    # 我们仅捕获 ``_parse_args`` 中额外抛出的 ValueError（来自 validate_config_names
    # 或 --k 自定义校验），把它们映射为 exit 2 并打印 stderr。
    try:
        run_config = _parse_args(argv)
    except ValueError as exc:
        # 参数合法性校验错误（未知 config 名、--k 非正整数）→ exit 2
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    # ---- 执行评测 -------------------------------------------------------
    try:
        asyncio.run(run_eval(run_config))
    except KeyboardInterrupt:
        # Ctrl+C：不捕获，让 Python 默认行为（exit 130）生效；
        # 显式 raise 而不是 re-raise 是为了避免被更外层的 except Exception 吞掉。
        raise
    except DatasetValidationError as exc:
        # 数据集违约：把每一条违约逐行打到 stderr（Requirement 11.4 / 11.5）。
        print(
            f"ERROR: dataset validation failed with "
            f"{len(exc.violations)} violation(s):",
            file=sys.stderr,
        )
        for v in exc.violations:
            # 每条违约消息前缀为 "  - "，便于与其他 stderr 输出区分
            print(f"  - {v}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        # dataset / corpus 路径不存在：映射为参数/数据集错误 exit 2
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:
        # run_eval 内部的 ValueError（理论上仅发生在参数兜底分支）→ exit 2
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except _HealthCheckError:
        # full profile 依赖探活失败：stderr 已在 run_eval 中打印 → exit 3
        return 3
    except Exception as exc:
        # 其余运行期异常（Milvus 超时、embedding HTTP 非 2xx、Python 逻辑错误）
        # → exit 3。类名与简短消息一起打印，便于 CI 日志定位根因。
        print(
            f"ERROR: runtime failure: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 3

    # 正常完成 → exit 0（Requirement 16.7）
    return 0
