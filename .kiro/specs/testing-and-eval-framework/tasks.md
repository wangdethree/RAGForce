# 实施计划：测试与评测框架

## Overview

基于 `design.md`（设计先行）与 `requirements.md`，本实现计划落地两个互补的支柱：

- **Scope A — 核心测试套件**（`backend/tests/`）：单元、集成、API 契约、Hypothesis 属性测试
- **Scope B — 检索质量评测框架**（`backend/eval/`）：中文数据集、入库、runner、Markdown 报告

实现顺序遵循"先脚手架、再 Fakes、再单元/属性、再集成、再 API、最后 eval"的增量路径，每个任务都建立在前一步之上，避免出现孤立未接线的代码。实现语言为 Python 3.11+，不修改生产代码的业务逻辑。

> 🇨🇳 **强制要求**：本项目所有实现代码（`.py` 文件）必须带上**中文注释**（模块 docstring、类/函数 docstring、关键逻辑的行内注释）。每个"写代码"子任务的描述末尾都会再次提醒执行者遵守此约定。

## Tasks

- [x] 1. 扩展 `backend/pyproject.toml` 并搭建测试/评测目录骨架
  - 在 `[project.optional-dependencies].dev` 追加：`pytest>=8`、`pytest-asyncio>=0.23`、`pytest-cov>=4.1`、`hypothesis>=6.98`、`httpx>=0.26`、`aiosqlite>=0.19`、`reportlab>=4.0`、`respx>=0.20`（可选）、`ruff`、`mypy`
  - 配置 `[tool.pytest.ini_options]`：`minversion`、`asyncio_mode="auto"`、`testpaths=["tests"]`、`pythonpath=["src"]`、`--strict-markers`、`--strict-config`、`--cov=src`、`--cov-fail-under=60`、`--cov-report=term-missing`、`--cov-report=xml`
  - 注册 6 个 marker（含中文描述）：`unit`、`integration`、`api`、`property`、`slow`、`docker`
  - 配置 `[tool.coverage.run]`（`branch=true`、`source=["src/services","src/api"]`、`omit=["src/worker/*","src/main.py"]`）与 `[tool.coverage.report]`
  - 生产依赖 `[project].dependencies` 不得新增任何测试专用库
  - 创建目录骨架（含 `__init__.py`）：`backend/tests/`、`backend/tests/fakes/`、`backend/tests/fixtures/`、`backend/tests/unit/`、`backend/tests/integration/`、`backend/tests/api/`、`backend/tests/properties/`、`backend/eval/`、`backend/eval/profiles/`、`backend/eval/datasets/corpus/`、`backend/eval/reports/`（带 `.gitkeep`）
  - 更新 `.gitignore` 排除 `backend/eval/reports/*.md`
  - 🇨🇳 所有新增 `__init__.py` 用中文 docstring 说明包用途；TOML 新增段落添加中文注释
  - _Requirements: 1.6, 9.7, 10.1, 10.2, 10.3, 10.5, 11.1, 17.1, 19.6_

- [x] 2. 实现 Fakes 适配层（`backend/tests/fakes/`）
  - [x] 2.1 实现 `tests/fakes/embedding.py` — `FakeEmbeddingService`
    - 基于 2/3-char shingle + SHA256 哈希构造 1024 维确定性向量，再做 L2 归一化
    - 暴露 `embed_batch(texts)`、`embed_single(text)`、`calls: list[str]` 调用日志
    - 零向量保护；相同输入必须产生相同向量
    - 🇨🇳 模块 docstring、类 docstring、`_vec` 内哈希/归一化步骤均需添加中文注释
    - _Requirements: 18.3, 19.1, 19.6_

  - [x] 2.2 实现 `tests/fakes/dense_searcher.py` — `InMemoryDenseSearcher`
    - 内存 `store: dict[str, list[dict]]`（字段 `chunk_id / document_id / content / content_type / embedding`）
    - 提供 `seed(kb_id, records)` 与 `async search(kb_id, query_embedding, top_k)`，使用 cosine 相似度
    - 空 kb、零向量情况返回 `[]` 不抛异常
    - 🇨🇳 对字段含义、cosine 公式、top_k 截取添加中文注释
    - _Requirements: 6.1, 6.2, 18.3, 19.1_

  - [x] 2.3 实现 `tests/fakes/sparse_searcher.py` — `InMemorySparseSearcher`
    - 使用 `re.findall(r"[A-Za-z0-9]+|[\u4e00-\u9fff]", s.lower())` 做中英混排分词
    - 使用 `Counter` 交集计算词元重叠分数，只保留 `score > 0` 的命中
    - 🇨🇳 中文注释说明分词规则与打分口径
    - _Requirements: 3.2, 6.3, 18.3, 19.1_

  - [x] 2.4 实现 `tests/fakes/reranker.py` — `FakeRerankerService`
    - 复用 sparse_searcher 的 `_tokenize` / `_overlap` 对候选重打分
    - **严格**保证：输出 `chunk_id` 集合 ⊆ 输入 `candidates` 的 `chunk_id` 集合（仅重打分、不引入新候选）
    - 🇨🇳 中文注释强调"保持候选集"不变式
    - _Requirements: 4.1, 4.2, 18.3, 19.1_

  - [x] 2.5 实现 `tests/fakes/query_rewriter.py` — `FakeQueryRewriter`
    - 构造参数 `variants: list[str] | None`（默认恒等变换）
    - `rewrite(query)` 返回列表首元素始终是原始 query，保证回退行为可测
    - 🇨🇳 中文注释说明"首元素为原始 query"的契约
    - _Requirements: 1.3, 3.4, 18.3, 19.1_

  - [x] 2.6 实现 `tests/fakes/deepseek.py` — `FakeDeepSeekChat`
    - `generate(query, context_chunks, history=None)` 返回罐头 `ChatResponse`（`answer` 含上下文摘要、`citations` 由 context_chunks 派生、`content` 截断到 200 字符）
    - `generate_stream(...)` 返回最小化 SSE delta（不发起网络请求）
    - 🇨🇳 中文注释强调"永不发起真实网络请求"
    - _Requirements: 7.4, 9.5, 19.1, 19.6_

- [ ] 3. 实现核心 Fixtures（`backend/tests/conftest.py` 与 `tests/fixtures/`）
  - [-] 3.1 实现 `tests/fixtures/sample_files.py` — 运行时生成 PDF/DOCX
    - `build_sample_pdf() -> bytes`：`reportlab` 生成 1-2 页含中英文的 PDF
    - `build_sample_docx() -> bytes`：可选 `python-docx` 分支（未安装则 `importorskip`）
    - 仓库中 **SHALL NOT** 提交任何二进制样例
    - 🇨🇳 中文注释描述每步（canvas 创建、段落写入、bytes 返回）
    - _Requirements: 9.6, 7.2_

  - [-] 3.2 实现 `tests/fixtures/seeded_kb.py` — 样例记录工厂
    - 纯函数 `sample_records(kb_id) -> list[dict]` 返回 5 条语义差异的中文 chunk（参见 design.md LLD-5）
    - 辅助 `build_kb_rows(session, kb_id)` 向 SQLite 写入 KnowledgeBase/Document 行（供 API 契约测试）
    - 🇨🇳 中文注释说明每条样例数据的语义意图
    - _Requirements: 3.1, 3.5, 7.1, 7.2, 7.5_

  - [-] 3.3 实现 `tests/conftest.py` 基础块：事件循环、Windows 策略与环境变量
    - session 级 `event_loop` fixture；Windows 上切换 `WindowsSelectorEventLoopPolicy`
    - 环境变量兜底：`DEEPSEEK_API_KEY=test`、`UPLOAD_DIR=./.test_uploads`
    - 🇨🇳 中文注释说明 Windows 策略切换的必要性
    - _Requirements: 9.5, 20.1, 20.3, 20.6_

  - [~] 3.4 实现 `conftest.py` 数据库部分：内存 SQLite 引擎与会话
    - `async_engine` fixture：`sqlite+aiosqlite:///:memory:` + `Base.metadata.create_all`
    - `db_session` fixture：per-test `AsyncSession` 基于 `async_sessionmaker`
    - 启动阶段显式 `import models` 确保全部表注册到 `Base.metadata`
    - 🇨🇳 中文注释说明 `expire_on_commit=False` 的用意
    - _Requirements: 9.5, 19.2, 20.6_

  - [~] 3.5 实现 `conftest.py` FastAPI 部分：`app` 与 `async_client` fixtures
    - 通过 `app.dependency_overrides[get_db]` 注入 SQLite 会话工厂
    - 拆解阶段调用 `app.dependency_overrides.clear()` 避免跨用例污染
    - `async_client` 基于 `httpx.AsyncClient(transport=ASGITransport(app=app))`
    - 🇨🇳 中文注释说明"进程内 ASGI 驱动、无需 uvicorn"
    - _Requirements: 7.6, 19.2, 19.5_

  - [~] 3.6 实现 `conftest.py` Fakes 注入 fixtures
    - 单体 fixtures：`fake_embedding`、`fake_dense`、`fake_sparse`、`fake_reranker`、`fake_query_rewriter`、`fake_deepseek`
    - 均通过 `monkeypatch.setattr` 替换生产单例（`services.retrieval.retriever.*`、`api.v1.chat.deepseek_chat`、`services.ingestion.embedder.embedding_service`）
    - 组合 fixture `wired_pipeline` 一次性接入检索管线所需的 5 个 Fakes
    - `seeded_kb` fixture 调用 `sample_records`，为每条 content 确定性计算 embedding 并 seed 到 dense/sparse
    - 🇨🇳 每个 fixture 写中文 docstring 说明用途、作用域与拆解行为
    - _Requirements: 3.1, 3.5, 19.1, 19.3, 19.5_

- [ ] 4. 实现纯逻辑单元测试（`backend/tests/unit/`）
  - [ ]* 4.1 `tests/unit/test_chunker.py`
    - 覆盖：空文本、仅空白、单段短文本、多段长文本、超长单段、中英混排、`content_type` 字段取值、`index` 连续单调
    - `@pytest.mark.unit`；使用 `ParsedDocument` schema 构造输入
    - 🇨🇳 每个用例添加中文注释说明意图与断言边界
    - _Requirements: 1.1, 1.7, 8.5, 10.5_

  - [ ]* 4.2 `tests/unit/test_fusion.py`
    - 覆盖：两路空、单路保持顺序、相同 chunk_id 分数相加且排在前列、不同 `k` 对分数幅度的影响、dense/sparse 角色对称性
    - 🇨🇳 中文注释标注每个不变式对应的设计点
    - _Requirements: 1.2, 1.7, 10.5_

  - [ ]* 4.3 `tests/unit/test_query_rewriter.py`
    - 覆盖：原始 query 始终包含在返回列表；DeepSeek 异常时退化为仅含原始 query 的列表
    - 借 `FakeDeepSeekChat` 异常分支或 `respx` 注入 HTTP 错误
    - 🇨🇳 中文注释说明回退行为的契约
    - _Requirements: 1.3, 1.7, 10.5_

  - [ ]* 4.4 `tests/unit/test_context_assembly.py`
    - 覆盖：空 chunks → 空字符串/空结构；非空 → 包含 content 片段与来源元数据
    - 🇨🇳 中文注释标注期望输出的结构键
    - _Requirements: 1.4, 1.7, 10.5_

- [~] 5. Checkpoint — 单元层全绿
  - 执行 `pytest -m unit`；确保 2 秒内通过
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Hypothesis strategies 与 RRF 属性测试
  - [-] 6.1 实现 `tests/properties/strategies.py`
    - 定义 `chunk_ids`、`contents`、`records`、`unique_records` 通用 strategies
    - 覆盖 CJK、ASCII、空白、超长字符串的生成器
    - 🇨🇳 对每个策略（尤其 `unique_by`、长度上下界）添加中文注释
    - _Requirements: 2.7, 8.6_

  - [ ]* 6.2 Write property test for RRF fusion — **Property 1: RRF 输出是输入并集的子集**
    - **Validates: Requirement 2.1**
    - 文件 `tests/properties/test_rrf_properties.py`；`max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明"输出 chunk_id ⊆ dense∪sparse"
    - _Requirements: 2.1, 2.7, 2.8_

  - [ ]* 6.3 Write property test for RRF fusion — **Property 2: RRF 输出中 chunk_id 去重**
    - **Validates: Requirement 2.2**
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明不变式与 Counter 判重思路
    - _Requirements: 2.2, 2.7, 2.8_

  - [ ]* 6.4 Write property test for RRF fusion — **Property 3: RRF 输出按分数非递增排序**
    - **Validates: Requirement 2.3**
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明与 `sorted(reverse=True)` 的等价断言
    - _Requirements: 2.3, 2.7, 2.8_

  - [ ]* 6.5 Write property test for RRF fusion — **Property 4: RRF 晋升单调**
    - **Validates: Requirement 2.4**
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明"提升目标到 dense 首位 → 融合分不降低"
    - _Requirements: 2.4, 2.7, 2.8_

  - [ ]* 6.6 Write property test for RRF fusion — **Property 5: RRF 的 k 参数平滑单调**
    - **Validates: Requirement 2.5**
    - `k1 < k2` → `var(scores|k=k2) <= var(scores|k=k1) + 1e-9`；`max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明方差容差
    - _Requirements: 2.5, 2.7, 2.8_

  - [ ]* 6.7 Write property test for RRF fusion — **Property 6: RRF 共现提升**
    - **Validates: Requirement 2.6**
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明"共现提升"的数学直觉
    - _Requirements: 2.6, 2.7, 2.8_

- [ ] 7. 检索管线集成测试（`backend/tests/integration/`）
  - [~] 7.1 `tests/integration/test_retriever_pipeline.py` 基础组合用例
    - 覆盖 `(use_hybrid, use_rerank, use_query_rewrite)` 的 `(F,F,F)`、`(T,F,F)`、`(T,T,F)`、`(T,T,T)` 四种组合
    - 每种组合断言：`len(results) <= top_k`、`chunk_id` 唯一、按分数降序、`latency_ms >= 0`
    - `use_hybrid=False` 时 `sparse_searcher.search` 未被调用（在 Fake 上记录 `calls` 或检测 `store` 未被查询）
    - `use_rerank=False` 时 reranker 未被调用
    - query_rewriter 多变体命中相同 chunk 时最终结果仍去重
    - 同一 `(kb_id, query, 配置)` 两次调用除 `latency_ms` 外字段等价（幂等）
    - `@pytest.mark.integration`
    - 🇨🇳 每个用例加中文注释说明断言针对哪条需求/标志开关
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7_

  - [~] 7.2 `similarity_threshold` 过滤语义集成用例
    - 阈值 0 不丢弃任何候选；阈值 1.1 返回 `[]`；阈值越高结果越少（单调）
    - 所有返回结果的 `score >= threshold`
    - 🇨🇳 中文注释说明阈值语义与单调性方向
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 3.7_

  - [~] 7.3 空 KB / 空 query / 空白 query 集成用例
    - 不存在的 `kb_id`：返回 `results=[]`、`total=0`，不抛异常
    - 合法但空的 kb：返回空
    - `query == ""` 或仅空白：返回空，**且不触发 embedding 批量调用**（通过 `fake_embedding.calls` 断言）
    - 🇨🇳 中文注释标注不同退化输入分支
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [~] 7.4 `tests/integration/test_ingestion_pipeline.py`
    - 复用真实 `DocumentChunker` + Fake embedder + Fake indexer
    - 端到端串联 chunk → embed → index；断言存储包含所有 chunk，chunk_id 稳定
    - `@pytest.mark.integration`
    - 🇨🇳 中文注释串联"解析 → 切分 → 向量化 → 索引"四步
    - _Requirements: 8.2, 8.3, 8.4, 19.1_

  - [ ]* 7.5 Write property test for retriever — **Property 7: Retriever 返回 top_k 子集且去重**
    - **Validates: Requirements 3.1, 3.4**
    - 文件 `tests/properties/test_retriever_properties.py`；`max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 3.1, 3.4, 2.7_

  - [ ]* 7.6 Write property test for retriever — **Property 8: 重排保持候选集**
    - **Validates: Requirements 4.1, 4.2, 4.3, 4.5**
    - `use_rerank=True` + `similarity_threshold=0` → 输出 `chunk_ids` ⊆ rerank 前候选集合；违约 id 打印
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [ ]* 7.7 Write property test for retriever — **Property 9: similarity_threshold 过滤单调**
    - **Validates: Requirements 5.1, 5.2, 5.4, 5.5**
    - `T_low < T_high` → `len(results_high) <= len(results_low)`，所有结果 `score >= T`
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 5.1, 5.2, 5.4, 5.5_

  - [ ]* 7.8 Write property test for retriever — **Property 10: 空知识库与空查询的优雅处理**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4**
    - 不存在的 kb / 合法但空的 kb / `query==""` / 仅空白 query → 均返回 `results==[]` 且不抛异常
    - 空 query 不得触发 embedding 的批量调用
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.6_

  - [ ]* 7.9 Write property test for retriever — **Property 15: 检索的确定性幂等**
    - **Validates: Requirements 3.6, 18.2, 18.3**
    - 同一输入两次调用 → 除 `latency_ms` 外字段等价
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明比较时需剥离 `latency_ms`
    - _Requirements: 3.6, 18.2, 18.3_

- [ ] 8. Chunker 属性测试（`backend/tests/properties/test_chunker_properties.py`）
  - [ ]* 8.1 Write property test for chunker — **Property 11: Chunker 大小上界**
    - **Validates: Requirement 8.1**
    - 对 `chunk_size=S`，每个 chunk `len(content) <= 2*S`（段落边界温和溢出）
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明容差来源
    - _Requirements: 8.1, 8.6_

  - [ ]* 8.2 Write property test for chunker — **Property 12: Chunker 信息无损**
    - **Validates: Requirement 8.2**
    - 所有文本型 chunk 按 index 拼接后包含原文每个非空白字符
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释说明"非空白字符集"的判定口径
    - _Requirements: 8.2, 8.6_

  - [ ]* 8.3 Write property test for chunker — **Property 13: Chunker index 连续单调**
    - **Validates: Requirement 8.3**
    - 产出 chunk 的 `index` 构成 `0..N-1` 的连续递增序列
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 8.3, 8.6_

  - [ ]* 8.4 Write property test for chunker — **Property 14: Chunker content_type 枚举封闭**
    - **Validates: Requirement 8.4**
    - 每个 chunk `content_type ∈ {"text","image","table"}`
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 8.4, 8.6_

  - [ ]* 8.5 Write property test for chunker — 空/空白输入返回空列表
    - **Validates: Requirement 8.5**
    - 空文本或仅空白 → 返回 `[]` 且不抛异常
    - `max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 8.5, 8.6_

- [~] 9. Checkpoint — integration + property 全绿
  - 执行 `pytest -m "integration or property"`；预期 10 秒内完成
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 10. FastAPI 契约测试（`backend/tests/api/`）
  - [~] 10.1 `tests/api/test_knowledge_bases_api.py`
    - 覆盖 `POST/GET/GET {id}/DELETE /api/v1/knowledge-bases`，断言状态码 `201/200/200|404/204`
    - `@pytest.mark.api`；使用 `async_client` fixture
    - 🇨🇳 中文注释标注每次请求期望的状态码与响应字段
    - _Requirements: 7.1, 7.6, 7.7, 19.2_

  - [~] 10.2 `tests/api/test_documents_api.py`
    - 使用 `build_sample_pdf()` 生成内存 PDF 以 multipart 提交
    - 覆盖上传、列表、详情三个端点
    - 🇨🇳 中文注释说明 multipart 构造步骤
    - _Requirements: 7.2, 7.6, 7.7, 9.6_

  - [~] 10.3 `tests/api/test_retrieval_api.py`
    - 断言响应包含 `query/results/total/latency_ms`；每个 result 至少含 `chunk_id/document_id/content/score`
    - 覆盖 `kb_id` 不存在场景（选定 `200+空` 或 `404` 其一并固定）
    - 🇨🇳 中文注释描述 schema 约束
    - _Requirements: 6.5, 7.3, 7.6, 7.7_

  - [~] 10.4 `tests/api/test_chat_api.py`
    - 依赖 `fake_deepseek` + `seeded_kb`
    - 断言非流式响应包含 `answer`(str) 与 `citations`(list[dict]，每项含 `chunk_id/content/score`)
    - 🇨🇳 中文注释说明 Fake 回答的拼装约定
    - _Requirements: 7.4, 7.6, 7.7_

  - [~] 10.5 `tests/api/test_audit_logs_api.py`
    - 覆盖分页 `page/page_size` 与时间/用户/动作三类过滤
    - 响应包含 `items/total/page/page_size`
    - 🇨🇳 中文注释标注每种查询参数组合的期望
    - _Requirements: 7.5, 7.6, 7.7_

- [ ] 11. 评测指标纯函数与测试（`backend/eval/metrics.py`）
  - [-] 11.1 实现 `backend/eval/metrics.py` 四个纯函数
    - `recall_at_k(relevant, retrieved, k)`：`|set(retrieved[:k]) ∩ relevant| / |relevant|`；空 relevant → 0.0
    - `mrr_at_k(relevant, retrieved, k)`：前 k 条中首次命中位置倒数；未命中 → 0.0
    - `ndcg_at_k(relevant, retrieved, k)`：二值相关性 + `log2(i+1)` 折扣，理想 DCG 归一化；0 命中 → 0.0
    - `percentile(values, p)`：空输入 → 0.0
    - 🇨🇳 每个公式用中文注释写出数学定义与边界处理
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [ ]* 11.2 `tests/unit/test_metrics.py`
    - 覆盖典型输入、空输入、全命中、全未命中、`k` 超过检索长度
    - `@pytest.mark.unit`
    - 🇨🇳 中文注释说明每个边界用例对应的数学语义
    - _Requirements: 1.5, 1.7, 14.7_

  - [ ]* 11.3 Write property test for metrics — **Property 16: 评测指标取值域**
    - **Validates: Requirements 14.2, 14.3, 14.4, 14.7**
    - `0 <= recall_at_k <= 1`、`0 <= mrr_at_k <= 1`、`0 <= ndcg_at_k <= 1`；空 relevant 或 0 命中时恒为 0
    - 文件 `tests/properties/test_metrics_properties.py`；`max_examples >= 100`；`@pytest.mark.property`
    - 🇨🇳 中文注释
    - _Requirements: 14.2, 14.3, 14.4, 14.7_

- [ ] 12. 评测数据集（`backend/eval/datasets/`）
  - [-] 12.1 生成 5 篇中文语料 Markdown 文件
    - 文件名固定：`doc_01_rag.md`、`doc_02_milvus.md`、`doc_03_bge.md`、`doc_04_rrf.md`、`doc_05_deepseek.md`
    - UTF-8 编码；单文件 3 KB ~ 30 KB
    - 🇨🇳 每篇开头用 HTML 注释或首段中文说明写作意图（不含 API key/PII）
    - _Requirements: 12.1, 12.2_

  - [~] 12.2 生成 `backend/eval/datasets/qa_zh.jsonl`
    - 20 ~ 30 条中文 QA（JSON Lines，每行一个对象）
    - 必填：`qid`、`query`、`relevant_doc_ids`（非空，元素为 corpus basename 去扩展名）
    - 可选：`relevant_chunk_ids`（`null` 或数组）、`answer`、`difficulty ∈ {"easy","medium","hard"}`
    - 难度分层：~12 easy、~8 medium、~5 hard（±2 浮动）
    - 每篇 corpus 文档至少作为一条 QA 的 ground truth 出现
    - 🇨🇳 JSONL 文件不允许行内注释；构造过程的理由写到 12.3 的 README 中
    - _Requirements: 11.1, 11.2, 11.3, 12.3, 12.4, 12.5_

  - [~] 12.3 撰写 `backend/eval/README.md`
    - 列出数据集规模、难度分层统计、每条 QA 的来源说明
    - 给出 `python -m eval.run --profile lite ...` 典型用法
    - 🇨🇳 通篇中文撰写，并在文件开头用 HTML 注释或引用块说明生成流程
    - _Requirements: 12.6, 17.5_

- [ ] 13. 评测配置、Profiles 与 CLI（`backend/eval/`）
  - [~] 13.1 实现 `backend/eval/config.py`
    - `@dataclass(frozen=True) RetrievalConfig`：`name`、`use_hybrid`、`use_rerank`、`use_query_rewrite`、`similarity_threshold`
    - 暴露 `PRESET_CONFIGS: list[RetrievalConfig]`（长度 4，顺序固定）：`dense_only`、`hybrid`、`hybrid_rerank`、`full`
    - `@dataclass RunConfig`：`profile`、`dataset_path`、`corpus_path`、`configs`、`k_values=[5,10]`、`kb_id="eval-kb"`、`output_dir="backend/eval/reports"`、`seed=42`
    - 🇨🇳 对每个字段写中文注释说明语义
    - _Requirements: 13.1, 13.2, 13.3, 13.4, 13.5_

  - [~] 13.2 实现数据集校验 `backend/eval/dataset.py`
    - 加载 JSONL，逐条校验必填字段与类型；逐条校验 `relevant_doc_ids` 指向 corpus 实存文件
    - 校验失败 → 抛自定义异常并由 runner 以 exit code 2 退出，stderr 输出违规 `qid`
    - 🇨🇳 中文注释说明字段契约（参见 requirements.md §11）
    - _Requirements: 11.2, 11.4, 11.5_

  - [~] 13.3 实现 `backend/eval/ingest.py`
    - `async ingest_corpus(corpus_dir, kb_id, *, chunker=None, embedder=None, indexer=None) -> dict[str, list[str]]`
    - 复用生产 `DocumentChunker` 与 `Chunk` schema；`embedder`/`indexer` 通过参数注入
    - 按 **稳定顺序**（文件名排序、chunk index 递增）迭代
    - 返回 `{doc_name: [chunk_id, ...]}`；runner 用来把 `relevant_doc_ids` 展开为 `relevant_chunk_ids`
    - 缺省 `relevant_chunk_ids` 时：评分阶段回退到基于 `document_id` 的成员判定
    - 🇨🇳 中文注释串联"读取 corpus → 解析 → 切分 → 向量化 → 索引 → 输出映射"
    - _Requirements: 11.6, 18.4_

  - [~] 13.4 实现 `backend/eval/profiles/lite.py`
    - `build_adapters()` 返回 Fakes 字典：`embedding/dense/sparse/reranker/query_rewriter`
    - `install(adapters)` 通过对 `services.retrieval.retriever` 模块属性赋值完成替换
    - 🇨🇳 中文注释强调"零 Docker、零真实 I/O"
    - _Requirements: 15.1, 15.2, 15.4, 19.3_

  - [~] 13.5 实现 `backend/eval/profiles/full.py`
    - `build_adapters()` 惰性 import 生产单例
    - `install(_)` 为空（生产接线已在 import 时生效）
    - 健康探活失败 → runner 以 exit code 3 退出并列出未连通依赖
    - 🇨🇳 中文注释说明"惰性 import 避免 unit/integration 层误触发 Milvus 客户端"
    - _Requirements: 15.3, 15.5, 15.6_

  - [~] 13.6 实现 `backend/eval/run.py` 与 `backend/eval/__main__.py`
    - argparse 参数：`--profile/--configs/--k/--dataset/--corpus/--kb-id/--output-dir/--seed`
    - 默认：`profile=lite`、`k=[5,10]`、`seed=42`、`output-dir=backend/eval/reports`
    - Windows 入口 `WindowsSelectorEventLoopPolicy`
    - 启动时固定 `random.seed`、`numpy.random.seed`（若已安装）、Hypothesis 全局 seed
    - 编排：profile.install → ingest_corpus → 加载/校验 QA → 对每个 `RetrievalConfig × k` 跑全部 query → 收集指标 → `report.render`
    - Full profile 在 ingest 与评测之间执行一次 warmup 查询（不计入 p50/p95）
    - 退出码：`0` 成功；`2` 参数/数据集错误（含 JSONL 字段、未知 config、corpus 缺文件）；`3` 运行期错误（warmup 失败、embedding HTTP 非 2xx、Milvus 超时）
    - `--help` → exit 0
    - 🇨🇳 对参数解析、profile 装配、主循环、异常映射各段添加中文注释
    - _Requirements: 13.3, 13.4, 15.5, 15.6, 16.1, 16.2, 16.3, 16.4, 16.5, 16.6, 16.7, 16.8, 16.9, 18.1, 18.4, 18.5, 20.2, 20.4, 20.5_

  - [~] 13.7 实现 `backend/eval/report.py`
    - 输出文件名 `YYYY-MM-DD-<profile>.md` 到 `--output-dir`
    - 元数据块：profile、数据集路径、条目数、参与配置、k 值、seed、wall time
    - 每个 k 一张 Summary 矩阵表（`Config | Recall@k | MRR@k | nDCG@k | p50 ms | p95 ms`，数值 ≤ 4 位小数）
    - Per-query breakdown 段：前 10 条 query 在各配置下 `✓ / ✗`
    - How to reproduce 段：可复制命令行与环境准备步骤
    - 脱敏：不输出 API key / secret / 内网主机名 / IP；相对路径锚点
    - 🇨🇳 中文注释说明每段结构与 GitHub 渲染兼容性
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 18.6_

- [ ] 14. 评测端到端烟测与可复现性属性
  - [~] 14.1 `tests/integration/test_eval_smoke.py`
    - lite profile 下调用 `run_eval(...)`：断言报告文件成功生成、不发起任何外部 I/O
    - 合理的底线门槛（`nDCG@5 >= 0.3`，仅作回归门槛，不是正确性门槛）
    - `@pytest.mark.integration`
    - 🇨🇳 中文注释说明测试边界与底线门槛的用意
    - _Requirements: 15.4, 17.1_

  - [ ]* 14.2 Write property test for eval — **Property 17: Lite profile 在固定种子下可复现**
    - **Validates: Requirements 18.1, 18.2, 18.3, 18.4**
    - 同一 `--seed` / 数据集 / `--configs` / `--k` 两次调用 `run_eval(...)`，断言 Recall/MRR/nDCG 完全一致
    - 文件 `tests/properties/test_eval_properties.py`；`max_examples >= 20`（执行开销较大）；同时打 `@pytest.mark.property` 与 `@pytest.mark.slow`
    - 🇨🇳 中文注释说明"在测试里直接调用 runner 主函数而非 subprocess"
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6_

- [~] 15. Checkpoint — API + Eval 烟测通过
  - 执行 `pytest -m "api or integration"`
  - 执行 `python -m eval.run --profile lite --configs dense_only,hybrid --k 5` 并确认报告产物
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 16. 质量门槛与 CI 友好性验证
  - [~] 16.1 验证 `pytest -m "not docker and not slow"` 在 4 核、无 Docker 机器 30 秒内完成
    - 若超时，审查 Hypothesis `max_examples` 与 session 级 fixtures 复用
    - 🇨🇳 如需新增调优相关代码（例如 Hypothesis profile），务必添加中文注释
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

  - [~] 16.2 验证 `--cov-fail-under=60` 生效
    - 若未达标，补充单元测试覆盖面（不得放宽门槛）
    - 🇨🇳 新增测试同样需要中文注释
    - _Requirements: 1.6, 9.7_

  - [~] 16.3 验证 Windows 事件循环兼容性
    - 在 Windows 执行 `pytest -m "not docker and not slow"` 与 `python -m eval.run --profile lite`
    - 确认无 `ProactorEventLoop` / `aiosqlite` / `httpx` 相关异常
    - 所有路径使用 `pathlib.Path` 或 `/` 分隔符
    - 🇨🇳 Windows 兼容性修补代码需要带中文注释
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5, 20.6_

  - [~] 16.4 验证未修改生产代码业务逻辑
    - grep 确认七个生产文件（`retriever.py`、`fusion.py`、`reranker.py`、`query_rewriter.py`、`chunker.py`、`embedder.py`、`deepseek_chat.py`）的逻辑未变
    - 仅允许新增 docstring / `typing.Protocol` 注解 / 不改变运行时行为的注释
    - 🇨🇳 若新增 docstring，用中文
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_

- [~] 17. Final checkpoint — 全量回归
  - `pytest -m "not docker and not slow"` 全绿、覆盖率 ≥ 60%、30 秒内完成
  - `python -m eval.run --profile lite` 成功生成 `YYYY-MM-DD-lite.md` 报告
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- 标记 `*` 的子任务为可选测试类（unit / integration / api / property），可在 MVP 阶段跳过；核心实现任务（无 `*`）不可跳过。
- 🇨🇳 **所有实现代码必须带中文注释**（模块 docstring、函数 docstring、关键逻辑行内注释），这是本项目的强制风格；每个"写代码"任务已在描述末尾重复提醒，执行者落地时请严格遵守。
- 每个任务都引用具体的 requirements 子条目（`_Requirements: X.Y_`），保证可追溯。
- Checkpoint 任务（5、9、15、17）确保每个增量阶段经过验证后再推进下一阶段。
- 属性测试（Property 1–17）完整覆盖 `design.md` 的 Correctness Properties 小节。
- 本特性 **SHALL NOT** 修改七个生产文件的业务逻辑；所有替换通过 `monkeypatch.setattr` 与 `app.dependency_overrides` 完成。

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6"] },
    { "id": 2, "tasks": ["3.1", "3.2", "3.3", "6.1", "11.1", "12.1"] },
    { "id": 3, "tasks": ["3.4", "4.1", "4.2", "4.3", "4.4", "11.2", "12.2", "13.1"] },
    { "id": 4, "tasks": ["3.5", "3.6", "6.2", "6.3", "6.4", "6.5", "6.6", "6.7", "8.1", "8.2", "8.3", "8.4", "8.5", "11.3", "12.3", "13.2", "13.4", "13.5"] },
    { "id": 5, "tasks": ["7.1", "7.2", "7.3", "7.4", "13.3"] },
    { "id": 6, "tasks": ["7.5", "7.6", "7.7", "7.8", "7.9", "10.1", "10.2", "10.3", "10.4", "10.5", "13.6"] },
    { "id": 7, "tasks": ["13.7"] },
    { "id": 8, "tasks": ["14.1"] },
    { "id": 9, "tasks": ["14.2", "16.1", "16.2", "16.3", "16.4"] }
  ]
}
```
