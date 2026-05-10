"""集成测试层（`@pytest.mark.integration`）。

本层使用 ``tests/fakes/*`` 中的内存适配器替换生产单例，串联以下管线：

- 检索管线：``Retriever.retrieve()``（query rewrite → dense/sparse → RRF → rerank）
- 入库管线：``DocumentChunker`` + Fake embedder + Fake indexer

硬性约束：零 Docker、零真实网络、全部用例合计须在 10 秒内完成
（Requirement 9.3、9.5）。具体测试由子任务 7.x / 14.1 实现。
"""
