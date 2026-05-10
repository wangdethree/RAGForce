"""评测运行 profile —— ``full``：对接真实 docker-compose 栈。

本 profile 使用生产代码中已经接线完成的 5 个模块级单例：

- ``services.ingestion.embedder.embedding_service``
  BGE-M3 HTTP 嵌入服务客户端
- ``services.retrieval.dense_searcher.dense_searcher``
  基于 Milvus 的稠密向量检索器
- ``services.retrieval.sparse_searcher.sparse_searcher``
  基于 PostgreSQL 全文索引的稀疏检索器（BM25 替身）
- ``services.retrieval.reranker.reranker_service``
  BGE-Reranker-v2-m3 重排序服务客户端
- ``services.retrieval.query_rewriter.query_rewriter``
  基于 DeepSeek 的查询改写器

与 ``lite`` profile 的关键区别：

1. **惰性 import**。生产模块（尤其是 ``dense_searcher``）在 import 时会初始化
   ``pymilvus`` 客户端并持有与 Milvus 的连接状态；如果在文件顶层就 import，任何
   单元测试或 integration 测试（本不应触碰 Milvus 的层次）一旦通过 Python 的
   包导入机制经过 ``eval.profiles`` 包，就会误触发真实客户端。因此本模块所有
   生产模块的 import 都只能出现在 ``build_adapters`` / ``health_check`` 函数
   体内。
2. **install 为空**。``full`` profile 直接复用生产单例，生产模块在首次 import
   时就已经完成了内部接线，无需像 ``lite`` 那样再通过
   ``monkeypatch.setattr`` 把 Fakes 塞进 ``services.retrieval.retriever``。
   保留 ``install(_) -> None`` 的空实现只是为了与 ``lite`` 对齐 profile 协议，
   让 ``run.py`` 能以同一种方式调用所有 profile。
3. **health_check 提供依赖探活**。返回"未连通依赖名称列表"。空列表 = 全健康；
   非空 = runner 将以 exit code 3 终止（对应 requirements §15.5）。
"""

# 注意：本模块顶层故意不 import 任何 services.* 子模块，避免 unit / integration
# 测试在收集 eval 包时无意间拉起 Milvus / HTTP 客户端。参见文件 docstring。


def build_adapters() -> dict[str, object]:
    """惰性 import 并返回生产级适配器字典。

    返回的 5 个键与 ``lite.build_adapters`` 完全对应，供 ``run.py`` 统一编排：

    - ``embedding``：``services.ingestion.embedder.embedding_service``
    - ``dense``：``services.retrieval.dense_searcher.dense_searcher``
    - ``sparse``：``services.retrieval.sparse_searcher.sparse_searcher``
    - ``reranker``：``services.retrieval.reranker.reranker_service``
    - ``query_rewriter``：``services.retrieval.query_rewriter.query_rewriter``

    这些都是生产模块首次被 import 时创建的模块级单例；在 full profile 下
    它们就是真实客户端（对接 Milvus / PostgreSQL / BGE-M3 / BGE-Reranker /
    DeepSeek），``run.py`` 不需要再做任何替换，直接交给
    ``services.retrieval.retriever.retriever.retrieve(...)`` 使用即可。

    惰性 import 是**强约束**：只有当调用方显式选择 full profile 时才会真正
    触发 ``pymilvus.connections.connect`` 之类的网络/客户端初始化。
    """
    # 惰性 import #1：BGE-M3 嵌入服务（httpx 客户端，按需创建）
    from services.ingestion.embedder import embedding_service

    # 惰性 import #2：Milvus 稠密检索（import 时会持有模块级 DenseSearcher 实例；
    # 真正的 connections.connect 延迟到首次 search 调用时执行，见 _ensure_connection）
    from services.retrieval.dense_searcher import dense_searcher

    # 惰性 import #3：PostgreSQL 全文索引稀疏检索
    from services.retrieval.sparse_searcher import sparse_searcher

    # 惰性 import #4：BGE-Reranker-v2-m3 重排序服务
    from services.retrieval.reranker import reranker_service

    # 惰性 import #5：基于 DeepSeek 的查询改写器
    from services.retrieval.query_rewriter import query_rewriter

    return {
        "embedding": embedding_service,
        "dense": dense_searcher,
        "sparse": sparse_searcher,
        "reranker": reranker_service,
        "query_rewriter": query_rewriter,
    }


def install(adapters: dict[str, object]) -> None:
    """full profile 的 ``install`` —— 故意留空。

    对于 lite profile，``install`` 需要用 ``monkeypatch.setattr`` 把 Fakes 注入
    到 ``services.retrieval.retriever`` 模块属性上，替换生产单例。

    对于 full profile，生产单例已经在各自模块 import 时被 ``retriever.py``
    直接 ``from ... import ...`` 绑定到 ``services.retrieval.retriever`` 模块
    命名空间中，因此无需额外的"接线"步骤。保留该空函数的唯一目的是让
    ``run.py`` 以 profile-agnostic 的方式调用：

    ``profile_module.install(profile_module.build_adapters())``

    不论 profile 是 lite 还是 full，调用形式相同，实际行为依赖具体 profile。
    """
    # 显式接收参数以保持函数签名一致；full profile 无需对 adapters 做任何事。
    del adapters
    return None


async def health_check(adapters: dict[str, object]) -> list[str]:
    """对 full profile 下的四类外部依赖进行轻量探活。

    返回值为**未连通依赖名称列表**：

    - 空列表 ``[]`` → 所有依赖健康，runner 可继续入库与评测
    - 非空列表 → runner 应以 exit code 3 终止，并把列表内容打到 stderr
      （对应 requirements §15.5）

    覆盖的依赖与探活动作：

    1. ``milvus``：调用 ``pymilvus.utility.list_collections()``，验证能与
       Milvus 建立连接并返回 collection 列表。
    2. ``postgresql``：通过 ``core.database.engine`` 执行 ``SELECT 1``，
       验证数据库 DSN 可连。
    3. ``embedding``：调用 ``embedding_service.embed_single("health")``，
       验证 BGE-M3 HTTP 服务在线（返回向量长度 > 0）。
    4. ``reranker``：调用 ``reranker_service.rerank(...)`` 传入一条占位
       候选，验证 BGE-Reranker HTTP 服务在线。

    任意一步抛出异常（超时、连接拒绝、协议错误、HTTP 非 2xx 等）均视为
    "未连通"，将该依赖名追加到返回列表中。注意：这里刻意**不**探活 DeepSeek
    chat 服务，因为 eval runner 的检索链路不依赖 chat 生成；DeepSeek 只在
    可选的端到端 chat 评测中才需要。
    """
    # 记录所有未连通依赖；最后统一返回
    down: list[str] = []

    # ------------------------------------------------------------------
    # 1) Milvus 探活：list_collections 是最轻量且不依赖具体 collection 的调用
    # ------------------------------------------------------------------
    try:
        # 惰性 import：仅当真正需要探活时才加载 pymilvus 与 settings
        from pymilvus import connections, utility

        from core.config import settings

        # 使用与生产相同的 alias，复用已建立的连接；若未连接则显式 connect 一次
        if "default" not in connections.list_connections():
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
            )
        # list_collections 不需要任何 collection 存在，只要服务在线就会成功
        utility.list_collections(using="default")
    except Exception:
        # 任何异常（超时、拒绝连接、认证失败）都视为 Milvus 未连通
        down.append("milvus")

    # ------------------------------------------------------------------
    # 2) PostgreSQL 探活：SELECT 1 是行业标准的最小活性探针
    # ------------------------------------------------------------------
    try:
        # 惰性 import：避免在 lite / 单元测试路径下触发 SQLAlchemy engine 构建
        from sqlalchemy import text

        from core.database import engine

        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        # DSN 错误、网络不可达、认证失败等 → PostgreSQL 未连通
        down.append("postgresql")

    # ------------------------------------------------------------------
    # 3) BGE-M3 嵌入服务探活：embed_single 一条短文本
    # ------------------------------------------------------------------
    try:
        # 从 adapters 里取出嵌入单例，避免重复 import
        embedding = adapters["embedding"]
        # 用一个极短的固定字符串做探针；注意：生产 EmbeddingService 会在
        # 网络失败时兜底返回 1024 维零向量而非抛异常，因此额外加一层零向量判断。
        vec = await embedding.embed_single("health")
        if not vec or all(x == 0.0 for x in vec):
            # 返回全零向量通常意味着上游 HTTP 调用已失败并被静默兜底
            raise RuntimeError("embedding service returned zero vector (likely unreachable)")
    except Exception:
        down.append("embedding")

    # ------------------------------------------------------------------
    # 4) BGE-Reranker 探活：用一条占位候选验证 HTTP 接口
    # ------------------------------------------------------------------
    try:
        reranker = adapters["reranker"]
        # 构造最小合法输入：一条候选，top_k=1
        probe_candidates = [
            {
                "chunk_id": "health-probe",
                "document_id": "health-probe",
                "content": "health",
                "content_type": "text",
                "score": 0.0,
            }
        ]
        reranked = await reranker.rerank("health", probe_candidates, top_k=1)
        # 生产 RerankerService 在 HTTP 失败时会兜底返回原 candidates 切片，
        # 因此不能仅凭"返回非空"判健康。此处要求返回项的 score 被更新过
        # （即 HTTP 成功路径会把 score 改为 reranker 模型的分数）。
        # 若返回项的 score 仍为 0.0 且与探针输入一致，则认为 HTTP 调用未真正成功。
        if not reranked:
            raise RuntimeError("reranker returned empty result")
        if reranked[0].get("score", 0.0) == 0.0:
            raise RuntimeError("reranker score unchanged (likely unreachable)")
    except Exception:
        down.append("reranker")

    return down
