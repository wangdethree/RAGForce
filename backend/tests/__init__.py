"""RAGForce 测试工程根包。

本包汇总 `backend/tests/` 下的全部测试资产，按功能划分为：

- ``fakes/``       —— 替代 Milvus / PostgreSQL BM25 / embedding / reranker /
                     DeepSeek 等外部依赖的内存 Fakes 实现
- ``fixtures/``    —— pytest fixtures 与样例数据工厂（PDF/DOCX 运行时生成）
- ``unit/``        —— 纯逻辑单元测试（chunker、RRF 融合、指标等）
- ``integration/`` —— 使用 Fakes 串联的检索 / 入库管线集成测试
- ``api/``         —— FastAPI 契约测试（httpx.AsyncClient + ASGITransport）
- ``properties/``  —— 基于 Hypothesis 的属性测试

全部测试在零 Docker、无真实外部网络的前提下运行，详见 `design.md` HLD-1。
"""
