"""评测 `lite` profile —— 零 Docker、零真实 I/O 的内存 Fakes 装配层。

本模块对应 `design.md` LLD-14 与 `tasks.md` 13.4。它负责把 `backend/tests/fakes/`
下的五个 Fake 适配器（embedding / dense / sparse / reranker / query_rewriter）
组装成生产检索管线所需的形状,并通过对 `services.retrieval.retriever` 与
`services.ingestion.embedder` **模块级变量赋值**的方式替换生产单例。

核心契约（Requirement 15.1 / 15.2 / 15.4 / 19.3）
------------------------------------------------

1. **零 Docker、零真实 I/O**：本 profile 完全走内存 Fakes,不启动或依赖任何
   Milvus / PostgreSQL / embedding HTTP / reranker HTTP / DeepSeek 进程。
2. **不修改生产代码**：仅通过对生产模块的模块级属性赋值完成替换,生产代码
   依旧按原样读取自身单例(变量在 import 期就被 Python 解释器解析为名字绑定;
   本模块在 `install()` 里对同一名字重新赋值,覆盖原单例)。
3. **确定性**：五个 Fake 的实现都保证"相同输入 → 相同输出",以此支撑评测
   可复现性(Requirement 18.3)。
4. **调用端等价**：`build_adapters()` 返回的字典键与 `full.py` 对齐,方便
   runner 层以同一套代码分发到两种 profile(Requirement 15.3)。

典型用法
--------

>>> from eval.profiles import lite
>>> adapters = lite.build_adapters()
>>> lite.install(adapters)            # 此后 retriever.retrieve(...) 全部走内存 Fakes
>>> # ... 调用 eval runner ...
"""

from __future__ import annotations

# 模块级常量:注入点清单,仅用于文档/测试可检视目的,运行时不会被读取。
# 下标 0 是目标模块的完全限定名,下标 1 是要覆盖的属性名,下标 2 是 adapters 字典的键。
# 这份清单与 Requirement 19.3 明确列出的五个注入点一致;同时为 ingest 阶段
# 额外注入 `services.ingestion.embedder.embedding_service`,以覆盖 ingest → embed 路径。
_RETRIEVER_INJECTION_POINTS: tuple[tuple[str, str, str], ...] = (
    ("services.retrieval.retriever", "dense_searcher", "dense"),
    ("services.retrieval.retriever", "sparse_searcher", "sparse"),
    ("services.retrieval.retriever", "reranker_service", "reranker"),
    ("services.retrieval.retriever", "query_rewriter", "query_rewriter"),
    ("services.retrieval.retriever", "embedding_service", "embedding"),
)

# 仅 ingest 阶段使用;单独列出是因为该模块不在检索路径上,但 runner 的
# `ingest_corpus(...)` 会直接读取 `services.ingestion.embedder.embedding_service`
# 来完成向量化,因此必须同步替换,否则会 fallback 到真实 HTTP 调用。
_INGESTION_INJECTION_POINTS: tuple[tuple[str, str, str], ...] = (
    ("services.ingestion.embedder", "embedding_service", "embedding"),
)


def build_adapters() -> dict[str, object]:
    """构造 `lite` profile 所需的五个 Fake 适配器并返回字典。

    返回
    ----
    dict[str, object]
        键固定为 ``{"embedding", "dense", "sparse", "reranker", "query_rewriter"}``,
        分别对应:

        * ``embedding``      —— ``tests.fakes.embedding.FakeEmbeddingService``
        * ``dense``          —— ``tests.fakes.dense_searcher.InMemoryDenseSearcher``
        * ``sparse``         —— ``tests.fakes.sparse_searcher.InMemorySparseSearcher``
        * ``reranker``       —— ``tests.fakes.reranker.FakeRerankerService``
        * ``query_rewriter`` —— ``tests.fakes.query_rewriter.FakeQueryRewriter``

    契约
    ----
    * **零 Docker、零真实 I/O**:Fakes 全部在内存中工作,不发起任何网络请求,
      不连接 Milvus、PostgreSQL、embedding / reranker HTTP 服务或 DeepSeek。
    * **函数内惰性导入**:把 ``tests.fakes.*`` 的 import 放在函数内部,避免
      本模块在 ``from eval.profiles import lite`` 时就强制要求 ``tests`` 包
      存在(例如分发到生产镜像时 ``tests/`` 可能被裁剪掉);同时也让 full
      profile 的调用链不会意外触发 Fake 的 import。
    * **每次调用返回新实例**:确保两次评测之间不共享内存状态(``InMemoryDense/
      SparseSearcher.store`` 不会跨调用串味),这对幂等性与可复现性很关键。
    """

    # 函数内惰性导入:避免 `eval.profiles` 包在加载期硬依赖 `tests.fakes.*`
    # 只有调用方真正选择 lite profile 时才拉起这些依赖
    from tests.fakes.dense_searcher import InMemoryDenseSearcher
    from tests.fakes.embedding import FakeEmbeddingService
    from tests.fakes.query_rewriter import FakeQueryRewriter
    from tests.fakes.reranker import FakeRerankerService
    from tests.fakes.sparse_searcher import InMemorySparseSearcher

    # 每个键对应生产检索管线中一个端口(参见 design.md LLD-3);
    # 返回顺序与 `full.py` 对齐,便于 runner 以同一套代码分发。
    return {
        # 向量化服务:生产对应 `services.ingestion.embedder.embedding_service`
        "embedding": FakeEmbeddingService(),
        # 稠密检索:生产对应 `services.retrieval.dense_searcher.dense_searcher`(Milvus)
        "dense": InMemoryDenseSearcher(),
        # 稀疏检索:生产对应 `services.retrieval.sparse_searcher.sparse_searcher`(PG BM25)
        "sparse": InMemorySparseSearcher(),
        # 交叉编码器重排:生产对应 `services.retrieval.reranker.reranker_service`
        "reranker": FakeRerankerService(),
        # 查询改写:生产对应 `services.retrieval.query_rewriter.query_rewriter`(DeepSeek)
        "query_rewriter": FakeQueryRewriter(),
    }


def install(adapters: dict[str, object]) -> None:
    """把 Fakes 注入到生产模块的模块级属性上,覆盖原单例。

    这是 `lite` profile 实现"零修改生产代码、零真实 I/O"的关键:Python 的
    ``import`` 语句会把被导入模块的**当前**属性值绑定到导入方的本地命名空间。
    本函数在 runner 启动时、任何 ``retrieve(...)`` 调用之前执行,通过对生产
    模块的属性直接赋值覆盖原单例;后续 `Retriever.retrieve(...)` 读取
    ``dense_searcher`` 等名字时,解析到的正是我们注入的 Fake 实例。

    参数
    ----
    adapters : dict[str, object]
        通常来自 ``build_adapters()`` 的返回值。必须包含五个键:
        ``embedding``、``dense``、``sparse``、``reranker``、``query_rewriter``。

    注入点(Requirement 19.3)
    ------------------------
    * ``services.retrieval.retriever.dense_searcher``   ← ``adapters["dense"]``
    * ``services.retrieval.retriever.sparse_searcher``  ← ``adapters["sparse"]``
    * ``services.retrieval.retriever.reranker_service`` ← ``adapters["reranker"]``
    * ``services.retrieval.retriever.query_rewriter``   ← ``adapters["query_rewriter"]``
    * ``services.retrieval.retriever.embedding_service``← ``adapters["embedding"]``
    * ``services.ingestion.embedder.embedding_service`` ← ``adapters["embedding"]``
      (ingest 阶段读取的是 ingestion.embedder 下的单例,单独覆盖一次)

    错误处理
    --------
    * ``adapters`` 缺键 → ``KeyError``(由调用方捕获,说明 profile 装配有误)
    * 目标生产模块结构重构(例如把单例变成工厂函数) → 允许显式
      ``ImportError`` / ``AttributeError`` 抛出,从而让问题在启动期被暴露,
      而不是悄悄走回真实 I/O 路径(Requirement 19.5)。

    返回
    ----
    None
        本函数仅产生副作用(模块属性赋值),不返回任何值。
    """

    # 函数内惰性导入生产模块,等到 `install()` 被显式调用才触发它们的 import 副作用;
    # 这样 `from eval.profiles import lite` 本身不会拉起 retriever / embedder,
    # 保证 unit / integration 层导入 `lite` 时仍然零副作用。
    import services.ingestion.embedder as embedder_mod
    import services.retrieval.retriever as retriever_mod

    # —— 检索管线注入点:覆盖 `services.retrieval.retriever` 模块内被 import 绑定的 5 个单例 ——
    # 原生产 retriever.py 通过 `from services.retrieval.dense_searcher import dense_searcher`
    # 等语句把对方的模块级单例**拷贝**到自己的命名空间;因此必须在 retriever 模块上
    # 重新赋值这 5 个名字,单纯改动源头模块不会影响已经绑定的引用。
    retriever_mod.dense_searcher = adapters["dense"]  # Milvus → InMemoryDenseSearcher
    retriever_mod.sparse_searcher = adapters["sparse"]  # PG BM25 → InMemorySparseSearcher
    retriever_mod.reranker_service = adapters["reranker"]  # HTTP reranker → FakeRerankerService
    retriever_mod.query_rewriter = adapters["query_rewriter"]  # DeepSeek 改写 → FakeQueryRewriter
    retriever_mod.embedding_service = adapters["embedding"]  # HTTP embedding → FakeEmbeddingService

    # —— ingest 阶段注入点:覆盖 `services.ingestion.embedder` 模块级单例 ——
    # 评测 runner 的 `ingest_corpus(...)` 若使用默认 embedder,会读取本模块上的
    # `embedding_service` 属性;这里同步替换,保证 ingest 阶段也走 Fake 向量化,
    # 不会因为生产 EmbeddingService 试图连 BGE-M3 HTTP 服务而触发真实 I/O。
    embedder_mod.embedding_service = adapters["embedding"]
