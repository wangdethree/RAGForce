"""评测运行 profile。

每个 profile 提供一对函数：

- ``build_adapters()`` —— 返回 ``{"embedding", "dense", "sparse", "reranker",
  "query_rewriter"}`` 五个键对应的适配器实例
- ``install(adapters)`` —— 将这些适配器装入 ``services.retrieval.retriever``
  等生产模块（通过属性赋值，不修改生产代码）

两套内置 profile：

- ``lite``：纯内存 Fakes，零 Docker、零网络 I/O（CI 默认选择）
- ``full``：对接真实 docker-compose 栈（Milvus、PostgreSQL、embedding /
  reranker HTTP 服务）

详见 Requirement 15 与子任务 13.4 / 13.5。
"""
