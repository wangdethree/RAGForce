"""外部依赖的 Fakes 适配层。

本包内每个模块对应 `design.md` LLD-3 中的一个端口（Port），提供确定性、
无真实 I/O 的内存实现，供单元、集成、API 以及评测 lite profile 共用：

- ``embedding.py``       —— ``FakeEmbeddingService``（哈希 shingle + L2 归一化）
- ``dense_searcher.py``  —— ``InMemoryDenseSearcher``（内存 cosine 检索）
- ``sparse_searcher.py`` —— ``InMemorySparseSearcher``（词元重叠打分）
- ``reranker.py``        —— ``FakeRerankerService``（保持候选集的重打分）
- ``query_rewriter.py``  —— ``FakeQueryRewriter``（恒等 / 可注入变体）
- ``deepseek.py``        —— ``FakeDeepSeekChat``（罐头回答，永不联网）

所有 Fakes 必须满足：**相同输入产生相同输出**，以保证可复现性
（Requirement 18.3）。具体实现由后续子任务 2.1 – 2.6 落地，本文件仅占位。
"""
