# Requirements Document: 测试与评测框架

## Introduction

RAGForce 当前尚未提供任何自动化测试，也没有检索质量的度量手段。本特性（Testing and Evaluation Framework）派生自同目录下已完成的 `design.md`（设计先行），落地两个互补的支柱：

**Scope A — 核心测试套件**（`backend/tests/`）：基于 pytest 的测试工程，覆盖纯逻辑单元测试（chunker、RRF 融合、query rewriter、context assembly、eval 指标）、基于 Fakes 替换外部依赖（Milvus、PostgreSQL BM25、embedding HTTP、reranker HTTP、DeepSeek、Celery）的检索管线集成测试、使用 `httpx.AsyncClient` + ASGI 传输驱动的 FastAPI API 契约测试，以及基于 Hypothesis 的属性测试。所有测试（排除 `docker`、`slow`）必须在零 Docker 环境下 30 秒内完成。

**Scope B — 检索质量评测框架**（`backend/eval/`）：一个可复现的离线评测工具，自带中文 QA 数据集、复用生产 ingestion 服务的语料入库脚本、按配置矩阵（`dense_only` / `hybrid` / `hybrid_rerank` / `full`）× k 值（默认 `{5, 10}`）迭代计算 Recall@k / MRR@k / nDCG@k / 延迟 p50/p95 的 runner，以及一份适合 README 引用的 Markdown 报告。

两个支柱共享同一套 Fakes 适配层，并通过 `lite` 与 `full` 两套 profile 在"零 Docker 本地开发"和"真实 docker-compose 栈"之间切换。本特性 SHALL NOT 修改生产代码的核心逻辑；所有替换通过 `monkeypatch.setattr` 作用于生产单例完成。

## Glossary

- **RAG (Retrieval-Augmented Generation)**：检索增强生成。先从知识库中检索相关片段，再交给大语言模型生成回答的架构模式。
- **RRF (Reciprocal Rank Fusion / 倒数排名融合)**：将多路检索结果按 `score += 1 / (k + rank)` 合并的无监督融合算法；参数 `k` 控制分数平滑度（项目默认 `k=60`）。
- **Dense Retrieval（稠密检索）**：基于向量相似度的语义检索，由 Milvus 提供。
- **Sparse Retrieval（稀疏检索）**：基于词项匹配的词汇检索（BM25 类），由 PostgreSQL 全文索引提供。
- **Hybrid Retrieval（混合检索）**：同时运行 dense retrieval 与 sparse retrieval，并用 RRF 融合结果。
- **Cross-Encoder（交叉编码器重排器）**：将 `query + candidate` 作为一对输入编码后输出相关性分数的重排模型，仅对候选集精排。
- **Recall@k**：召回率。前 k 条结果中命中的相关文档数占全部相关文档数的比例。
- **MRR (Mean Reciprocal Rank)**：平均倒数排名。首个命中位置的倒数之平均。
- **MRR@k**：仅在前 k 条结果内计算的 MRR。
- **nDCG@k (Normalized Discounted Cumulative Gain)**：归一化折损累积增益，对排名位置做 `log2` 折扣后归一化的排序质量指标。
- **PBT (Property-Based Testing / 基于属性的测试)**：通过"对所有输入 X，属性 P(X) 成立"的全称命题描述被测代码行为，并由框架（Hypothesis）自动生成大量随机样本验证。
- **EARS (Easy Approach to Requirements Syntax)**：用受限关键词（WHEN / WHILE / WHERE / IF / THEN / THE / SHALL）表达需求的句法规范。
- **Fake**：具备真实逻辑但使用简化实现（如内存字典代替 Milvus）的替代品，产出确定性输出。
- **Mock**：通常由框架自动生成、可预设返回值并记录调用的替身。本项目在端到端联通性测试上尽量避免使用 Mock。
- **Stub**：只返回预置常量、不含业务逻辑的简化替身（如 `FakeDeepSeekChat` 的"罐头回答"路径）。
- **Profile:lite（轻量 profile）**：完全基于内存 Fakes、零 Docker、可在 CI 中秒级完成的运行模式。
- **Profile:full（完整 profile）**：针对真实 docker-compose 栈（Milvus、PostgreSQL、embedding/reranker HTTP 服务）运行的模式。
- **Port（端口）**：在业务代码一侧定义的、与外部系统交互所需的 duck-typed 接口契约（见 `design.md` LLD-3）。
- **Adapter（适配器）**：端口的具体实现（生产用真实客户端，测试用 Fakes）。
- **Port / Adapter 模式（端口—适配器模式）**：六边形架构，将核心逻辑与外部依赖通过端口解耦；本项目以"生产单例 + monkeypatch 替换"的最小成本实现该模式。
- **Seeded KB（预置知识库）**：在测试开始前将一组确定性 `(chunk_id, document_id, content, embedding)` 记录写入 Fake Dense/Sparse 存储的 Fixture。
- **Test_Suite**：指 `backend/tests/` 下的完整 pytest 测试工程。
- **Eval_Framework**：指 `backend/eval/` 下的评测框架。
- **Retrieval_Pipeline**：指 `Retriever.retrieve()` 编排的"查询改写 → 稠密/稀疏检索 → RRF 融合 → 重排 → 阈值过滤"管线。
- **Report_Generator**：指 `backend/eval/report.py` 生成 Markdown 报告的组件。
- **CLI_Runner**：指 `python -m eval.run` 入口。

## Requirements

### Requirement 1：单元测试覆盖纯逻辑组件与覆盖率门槛

**User Story：** 作为一名开发者，我希望对 chunker、RRF 融合、query rewriter、context assembly、eval 指标这五类纯逻辑有覆盖充分的单元测试，并由覆盖率门槛守门，以便我在重构内部实现时能迅速发现回归。

#### Acceptance Criteria

1. THE Test_Suite SHALL 在 `backend/tests/unit/test_chunker.py` 中覆盖以下场景：空文本、仅空白文本、单段短文本、多段长文本、超长单段文本、中英混排文本、`content_type` 字段取值，以及 chunk index 的连续单调性。
2. THE Test_Suite SHALL 在 `backend/tests/unit/test_fusion.py` 中覆盖以下场景：两路输入均为空、单路输入保持顺序、dense 与 sparse 出现相同 `chunk_id` 时分数相加且该 id 排在前列、不同 `k` 参数对分数幅度的影响、以及 dense/sparse 顺序对称性。
3. THE Test_Suite SHALL 在 `backend/tests/unit/test_query_rewriter.py` 中至少覆盖：原始 query 本身 SHALL 始终包含在返回列表中；IF DeepSeek 调用抛出异常，THEN THE Query_Rewriter SHALL 回退到仅含原始 query 的列表。
4. THE Test_Suite SHALL 在 `backend/tests/unit/test_context_assembly.py` 中覆盖：WHEN chunks 列表为空，THE 组装函数 SHALL 返回空字符串或空结构；WHEN chunks 非空，THE 返回值 SHALL 包含每条 chunk 的 content 片段与来源元数据。
5. THE Test_Suite SHALL 在 `backend/tests/unit/test_metrics.py` 中覆盖 `recall_at_k`、`mrr_at_k`、`ndcg_at_k`、`percentile` 四个纯函数的典型输入、空输入、以及极端边界（全命中、全未命中、`k` 超过检索长度）。
6. WHEN 覆盖率（`coverage`）低于 60%，THE Test_Suite SHALL 以非零退出码失败（由 `--cov-fail-under=60` 强制）。
7. WHEN 任一单元测试用例执行，THE Test_Suite SHALL NOT 发起任何真实的 HTTP、数据库或向量检索 I/O。

---

### Requirement 2：RRF 融合正确性不变式

**User Story：** 作为一名开发者，我希望 RRF 融合的所有设计级不变式都被 Hypothesis 属性测试覆盖，以便随机生成的输入能发掘我手写单元测试漏掉的边界情况。

#### Acceptance Criteria

1. THE Test_Suite SHALL 为 `design.md` LLD-9 所列 **P1（子集性）** 编写属性测试：FOR ALL `(dense, sparse)`，`RRFusion().fuse(dense, sparse)` 返回结果的 `chunk_id` 集合 SHALL 是 `dense` 与 `sparse` 中所有 `chunk_id` 并集的子集。
2. THE Test_Suite SHALL 为 **P2（去重）** 编写属性测试：FOR ALL `(dense, sparse)`，融合结果中任意 `chunk_id` SHALL 至多出现一次。
3. THE Test_Suite SHALL 为 **P3（分数降序）** 编写属性测试：FOR ALL `(dense, sparse)`，融合结果 SHALL 按 `score` 非递增排序。
4. THE Test_Suite SHALL 为 **P4（晋升单调）** 编写属性测试：FOR ALL `(dense, sparse, target_idx)`，WHEN 将 `dense[target_idx]` 提升到 `dense` 首位，THE 目标 chunk 在融合结果中的 `score` SHALL 不降低。
5. THE Test_Suite SHALL 为 **P5（k 参数平滑单调）** 编写属性测试：FOR ALL `(dense, sparse, k1, k2)`，WHEN `k1 < k2`，THE `k=k2` 的融合结果的分数方差 SHALL 小于等于 `k=k1` 的分数方差（允许 `1e-9` 的数值容差）。
6. THE Test_Suite SHALL 为 **P6（共现提升）** 编写属性测试：WHEN 某个 `chunk_id` 同时出现在 `dense` 与 `sparse` 中，THE 该 id 在融合结果中的 `score` SHALL 不小于仅单路出现时的 `score`。
7. THE Test_Suite SHALL 为每条属性测试配置 `max_examples >= 100`，并使用 `@pytest.mark.property` 标记。
8. WHEN 某条属性测试失败，THE Test_Suite SHALL 通过 Hypothesis 自动缩减并打印最小反例。

---

### Requirement 3：检索管线集成测试覆盖标志组合

**User Story：** 作为一名开发者，我希望对 `Retriever.retrieve()` 的主要标志组合有集成测试，以便在修改管线编排逻辑时能验证 `use_hybrid` / `use_rerank` / `use_query_rewrite` 三个开关的每一种组合都按设计生效。

#### Acceptance Criteria

1. WHEN 调用 `retriever.retrieve(kb_id, query, top_k=N, use_hybrid=True, use_rerank=True)` 且 `seeded_kb` Fixture 就绪，THE Retrieval_Pipeline SHALL 返回 `len(results) <= N` 且所有 `chunk_id` 互不相同的 `RetrievalResponse`。
2. WHEN `use_hybrid=False`，THE Retrieval_Pipeline SHALL NOT 调用 `sparse_searcher.search`。
3. WHEN `use_rerank=False`，THE Retrieval_Pipeline SHALL NOT 调用 `reranker_service.rerank`，且结果 SHALL 按融合分数降序。
4. WHEN `FakeQueryRewriter` 被配置为返回多个变体且多个变体命中同一 chunk，THE Retrieval_Pipeline SHALL 在最终结果中去重该 chunk。
5. THE Test_Suite SHALL 覆盖 `(use_hybrid, use_rerank, use_query_rewrite)` 的至少以下 4 种组合：`(F,F,F)`、`(T,F,F)`、`(T,T,F)`、`(T,T,T)`，并对每种组合断言结果的结构性不变式（长度、唯一性、排序）。
6. WHEN 对同一 `(kb_id, query, 配置)` 连续两次调用 `retrieve`，THE Retrieval_Pipeline SHALL 返回除 `latency_ms` 外字段等价的两个响应（由确定性 Fakes 保证幂等）。
7. THE Test_Suite SHALL 为每个集成测试用例标记 `@pytest.mark.integration`。

---

### Requirement 4：重排序保持候选集不变

**User Story：** 作为一名开发者，我希望重排阶段只改变顺序、不产生或引入新的候选，以便我的召回阶段性能分析不会被重排阶段污染。

#### Acceptance Criteria

1. WHEN `use_rerank=True`，THE Retrieval_Pipeline SHALL 保证返回结果中每条 chunk 的 `chunk_id` 都曾出现在 rerank 调用前的融合候选集合中。
2. WHEN `FakeRerankerService.rerank(query, candidates, top_k)` 被调用，THE FakeRerankerService SHALL 返回一个列表，其 `chunk_id` 集合 SHALL 是 `candidates` 的 `chunk_id` 集合的子集。
3. THE Test_Suite SHALL 在 `backend/tests/properties/test_retriever_properties.py` 中为上述不变式编写 `@pytest.mark.property` 属性测试，`max_examples >= 100`。
4. IF rerank 输出中出现任何不在输入 `candidates` 中的 `chunk_id`，THEN THE Test_Suite SHALL 失败并指出该违约 id。
5. WHEN `use_rerank=True` 且 `similarity_threshold=0`，THE 结果的 `chunk_id` 集合 SHALL 是 rerank 前候选集合的子集。

---

### Requirement 5：`similarity_threshold` 过滤语义

**User Story：** 作为一名开发者，我希望 `similarity_threshold` 参数有明确、可测的过滤语义，以便我在调用检索 API 时能精确控制返回结果的最低分数门槛。

#### Acceptance Criteria

1. WHEN 调用 `retriever.retrieve(..., similarity_threshold=T)`，THE Retrieval_Pipeline SHALL 保证返回结果中每一条的 `score >= T`。
2. WHEN `similarity_threshold=0.0`，THE Retrieval_Pipeline SHALL NOT 因阈值过滤而丢弃任何候选。
3. WHEN `similarity_threshold=1.1`（大于任何合法分数），THE Retrieval_Pipeline SHALL 返回 `results == []`。
4. WHEN 对同一 `seeded_kb` 与同一 `query` 分别以 `similarity_threshold=T_low` 与 `similarity_threshold=T_high`（`T_low < T_high`）调用，THE `len(results_high) <= len(results_low)` SHALL 成立。
5. THE Test_Suite SHALL 为上述单调性编写 `@pytest.mark.property` 属性测试，`max_examples >= 100`。

---

### Requirement 6：空知识库与空查询的优雅处理

**User Story：** 作为一名开发者，我希望检索管线在面对空知识库、空查询、纯空白查询这类退化输入时返回空结果而不抛异常，以便上游服务可以安全处理这些边界。

#### Acceptance Criteria

1. WHEN 调用 `retrieve(kb_id=<不存在的 kb>, query=<任意字符串>)`，THE Retrieval_Pipeline SHALL 返回 `results == []` 且 `total == 0`，且 SHALL NOT 抛出异常。
2. WHEN 调用 `retrieve(kb_id=<合法但空的 kb>, ...)`，THE Retrieval_Pipeline SHALL 返回 `results == []` 且 SHALL NOT 抛出异常。
3. IF 入参 `query == ""`，THEN THE Retrieval_Pipeline SHALL 返回 `results == []` 且 SHALL NOT 触发 embedding 服务的批量调用。
4. IF 入参 `query` 仅由空白字符组成，THEN THE Retrieval_Pipeline SHALL 返回 `results == []` 且 SHALL NOT 抛出异常。
5. WHEN 调用 `POST /api/v1/retrieval` 传入不存在的 `kb_id`，THE API SHALL 返回 HTTP `200` 且响应体 `results == []`（或返回 HTTP `404` 并附带错误码；二者之一必须稳定一致，且由测试固定下来）。
6. THE Test_Suite SHALL 为以上场景分别编写 `@pytest.mark.integration` 或 `@pytest.mark.property` 测试用例。

---

### Requirement 7：FastAPI API 契约测试

**User Story：** 作为一名开发者，我希望对公开的 FastAPI 端点有契约测试，以便我在修改 schema 或路由时能立即发现对调用方可见的破坏性变更。

#### Acceptance Criteria

1. THE Test_Suite SHALL 在 `backend/tests/api/test_knowledge_bases_api.py` 中覆盖 `POST /api/v1/knowledge-bases`、`GET /api/v1/knowledge-bases`、`GET /api/v1/knowledge-bases/{id}`、`DELETE /api/v1/knowledge-bases/{id}` 四个端点，并分别断言状态码 `201`、`200`、`200`/`404`、`204`。
2. THE Test_Suite SHALL 在 `backend/tests/api/test_documents_api.py` 中覆盖文档上传、列表、详情三个端点；上传 SHALL 使用由 `reportlab` 在内存中生成的样例 PDF（multipart payload）。
3. THE Test_Suite SHALL 在 `backend/tests/api/test_retrieval_api.py` 中对 `POST /api/v1/retrieval` 断言响应 JSON 包含 `query`、`results`、`total`、`latency_ms` 四个键；`results` 中每项 SHALL 至少包含 `chunk_id`、`document_id`、`content`、`score` 四个字段。
4. THE Test_Suite SHALL 在 `backend/tests/api/test_chat_api.py` 中对非流式 `POST /api/v1/chat` 断言响应包含 `answer`（字符串）与 `citations`（数组）字段；`citations` 中每项 SHALL 至少包含 `chunk_id`、`content`、`score`。
5. THE Test_Suite SHALL 在 `backend/tests/api/test_audit_logs_api.py` 中覆盖分页（`page`、`page_size`）与时间、用户、动作三类过滤参数，并断言响应包含 `items`、`total`、`page`、`page_size` 四个键。
6. WHEN 任一 API 契约测试执行，THE Test_Suite SHALL 使用 `app.dependency_overrides` 注入的 SQLite 会话与 Fakes，SHALL NOT 触发真实外部 I/O。
7. THE Test_Suite SHALL 为每个 API 契约测试用例标记 `@pytest.mark.api`。

---

### Requirement 8：Chunker 大小边界与内容无丢失

**User Story：** 作为一名开发者，我希望 `DocumentChunker` 在任何合法输入下都满足大小上界与"信息无损"两项不变式，以便下游 embedding 与检索的输入质量被保证。

#### Acceptance Criteria

1. FOR ALL 非空 `ParsedDocument.text` 与任意 `chunk_size=S`，THE DocumentChunker SHALL 产出 `len(chunk.content) <= 2 * S` 的 chunks（容许段落边界造成的温和溢出）。
2. FOR ALL 非空 `ParsedDocument.text`，THE 所有文本型 chunks 按 `index` 顺序拼接后得到的字符串 SHALL 包含原始文本中每一个非空白字符（信息无损属性）。
3. FOR ALL 由 N 条 chunks 构成的输出，THE 所有 chunks 的 `index` 字段 SHALL 构成连续序列 `0, 1, ..., N-1`，单调递增且无跳跃。
4. FOR ALL chunks，THE `content_type` 字段 SHALL 取值于 `{"text", "image", "table"}`。
5. WHEN 输入文本为空或仅含空白，THE DocumentChunker SHALL 返回空列表，且 SHALL NOT 抛出异常。
6. THE Test_Suite SHALL 在 `backend/tests/properties/test_chunker_properties.py` 中为上述 5 条不变式各编写 `@pytest.mark.property` 属性测试，`max_examples >= 100`，并在 Hypothesis strategies 中覆盖 CJK、ASCII、空白、超长字符串等边界输入。

---

### Requirement 9：测试独立性与运行性能

**User Story：** 作为一名 CI 维护者，我希望在没有 Docker 的 CI runner 上全量跑排除 `docker`、`slow` 标记的测试能在 30 秒内完成，以便每次 PR 提交都能快速拿到反馈。

#### Acceptance Criteria

1. WHEN 在一台 4 核、未启动任何 Docker 服务、未配置真实 DeepSeek API key 的机器上执行 `pytest -m "not docker and not slow"`，THE Test_Suite SHALL 成功收集并运行单元、集成、API、属性四层测试，并 SHALL 在 30 秒内完成。
2. WHEN 执行 `pytest -m unit`，THE Test_Suite SHALL 在 2 秒内完成。
3. WHEN 执行 `pytest -m "integration or api"`，THE Test_Suite SHALL 在 10 秒内完成。
4. WHEN 执行 `pytest -m property`，THE Test_Suite SHALL 在 10 秒内完成不少于 100 examples × 18 条属性（P1–P6、R1–R8、C1–C5）的迭代。
5. WHEN 任一测试执行，THE Test_Suite SHALL NOT 依赖 Docker、真实 Milvus、真实 PostgreSQL、真实 embedding/reranker HTTP 服务、真实 DeepSeek 或任何外部网络。
6. THE Test_Suite SHALL 在内存中按需生成样例 PDF（借助 `reportlab`）与 DOCX（借助 `python-docx`）作为 fixture，SHALL NOT 将任何二进制样例文件提交到仓库。
7. WHERE CI 环境变量 `CI=true` 存在，THE Test_Suite SHALL 输出 `--cov-report=xml`，以便 CI 上传覆盖率报告。

---

### Requirement 10：测试分层标记体系

**User Story：** 作为一名开发者，我希望 pytest 注册一套清晰的分层 marker，以便我可以按层运行测试（如只跑 unit、只跑 property）或按环境跳过（跳过 docker、slow）。

#### Acceptance Criteria

1. THE Test_Suite SHALL 在 `backend/pyproject.toml` 的 `[tool.pytest.ini_options]` 中声明 `--strict-markers`。
2. THE Test_Suite SHALL 注册以下六个 marker，并在 `markers = [...]` 中附带描述：
   - `unit`：纯逻辑测试，无 I/O。
   - `integration`：带 Fakes 的管线测试，无网络/Docker。
   - `api`：FastAPI 契约测试。
   - `property`：Hypothesis 属性测试。
   - `slow`：耗时较长，默认不跑，通过 `-m slow` 显式开启。
   - `docker`：需要 docker-compose 栈，默认不跑，通过 `-m docker` 显式开启。
3. WHEN 某测试文件使用未注册的 marker，THE Test_Suite SHALL 因 `--strict-markers` 而启动失败。
4. WHEN 执行 `pytest -m "not docker and not slow"`，THE Test_Suite SHALL 收集并运行前四类标记的全部测试，并 SHALL 跳过 `slow` 与 `docker` 标记的测试。
5. THE Test_Suite SHALL 在每个测试文件内使用与其目录一致的 marker：`tests/unit/` 下使用 `unit`、`tests/integration/` 下使用 `integration`、`tests/api/` 下使用 `api`、`tests/properties/` 下使用 `property`。
6. THE Test_Suite SHALL 允许任一测试同时带有 `slow` 或 `docker` 附加 marker，以便将慢速/容器化测试从默认集合中剔除。

---

### Requirement 11：评测数据集文件格式

**User Story：** 作为一名性能优化者，我希望评测数据集有稳定的 JSONL 字段契约，以便我能按同样的格式扩展或替换 QA 集而不破坏下游 runner。

#### Acceptance Criteria

1. THE Eval_Framework SHALL 在 `backend/eval/datasets/qa_zh.jsonl` 中存放一个 JSON Lines 文件，每行 SHALL 是一个 JSON 对象且 SHALL NOT 包含注释。
2. THE JSONL 每条记录 SHALL 至少包含以下必填字段：
   - `qid`（字符串，稳定唯一）
   - `query`（中文字符串，长度 `>= 1`）
   - `relevant_doc_ids`（字符串数组，长度 `>= 1`，元素为 `backend/eval/datasets/corpus/` 中文件的 basename 不带扩展名）
3. THE JSONL 每条记录 SHALL 允许可选字段：
   - `relevant_chunk_ids`（字符串数组或 `null`；由 ingest 阶段填充）
   - `answer`（字符串；可选参考答案，v1 不用于评分）
   - `difficulty`（字符串，取值于 `{"easy", "medium", "hard"}`；用于分层统计）
4. WHEN 加载数据集，THE Eval_Framework SHALL 校验每条记录包含必填字段且类型正确；IF 校验失败，THEN THE CLI_Runner SHALL 以 exit code `2` 退出并在 stderr 打印违规的 `qid` 与原因。
5. WHEN `relevant_doc_ids` 中某元素在 `corpus/` 中无对应文件，THE CLI_Runner SHALL 以 exit code `2` 退出并指出缺失的 doc 名。
6. WHEN 某条记录的 `relevant_chunk_ids` 为 `null` 或缺省，THE Eval_Framework SHALL 在评分时回退到基于 `document_id` 的成员判定（即若 retrieved chunk 属于任一 `relevant_doc_ids` 中的文档，则视为命中）。

---

### Requirement 12：中文语料与 QA 对规模

**User Story：** 作为一名招聘/面试场景的读者，我希望评测数据集既真实又可复现，以便我不用自己准备 ground truth 就能评估 RAGForce 的检索效果。

#### Acceptance Criteria

1. THE Eval_Framework SHALL 在 `backend/eval/datasets/corpus/` 下提供恰好 5 篇中文 Markdown 文档，主题分别覆盖 RAG、Milvus、BGE、RRF、DeepSeek，文件命名 SHALL 为 `doc_01_rag.md`、`doc_02_milvus.md`、`doc_03_bge.md`、`doc_04_rrf.md`、`doc_05_deepseek.md`。
2. THE 每篇语料文档 SHALL 为 UTF-8 编码、单文件大小在 3 KB 至 30 KB 之间的合法 Markdown。
3. THE `qa_zh.jsonl` SHALL 包含 20 至 30 条 QA，全部为中文查询。
4. THE QA 集 SHALL 在 `difficulty` 字段上大致分层：约 12 条 `easy`（精确词匹配，sparse 主导）、约 8 条 `medium`（同义表达，dense 主导）、约 5 条 `hard`（跨文档综合，rerank/fusion 主导）；每档数量允许 `±2` 浮动。
5. THE QA 集 SHALL 在所有 `relevant_doc_ids` 上至少覆盖到 5 篇语料文档中的每一篇（即不存在从未作为 ground truth 出现的文档）。
6. THE Eval_Framework SHALL 在 `backend/eval/README.md` 中列出数据集规模、分层统计、以及每条 QA 的来源说明。

---

### Requirement 13：检索配置矩阵

**User Story：** 作为一名性能优化者，我希望评测框架预置四种典型检索配置，以便我能一键对比"加不加混合检索、加不加重排、加不加查询改写"带来的指标差异。

#### Acceptance Criteria

1. THE Eval_Framework SHALL 在 `backend/eval/config.py` 中以不可变对象（`@dataclass(frozen=True)`）提供以下四个预置 `RetrievalConfig`：
   - `dense_only`：`(use_hybrid=False, use_rerank=False, use_query_rewrite=False)`
   - `hybrid`：`(use_hybrid=True, use_rerank=False, use_query_rewrite=False)`
   - `hybrid_rerank`：`(use_hybrid=True, use_rerank=True, use_query_rewrite=False)`
   - `full`：`(use_hybrid=True, use_rerank=True, use_query_rewrite=True)`
2. THE Eval_Framework SHALL 以列表 `PRESET_CONFIGS` 暴露上述四个配置，并保证列表长度等于 4。
3. WHEN 调用 CLI 时未指定 `--configs`，THE CLI_Runner SHALL 默认对全部 `PRESET_CONFIGS` 四个配置执行评测。
4. WHEN `--configs` 参数包含未知配置名，THE CLI_Runner SHALL 以 exit code `2` 退出并在 stderr 列出合法配置名。
5. THE Eval_Framework SHALL 为每个 `RetrievalConfig` 在每个 `k ∈ --k` 下运行一遍，并在报告中分别计算 Recall@k / MRR@k / nDCG@k / latency_p50 / latency_p95。

---

### Requirement 14：评测指标计算公式

**User Story：** 作为一名性能优化者，我希望评测框架提供与学术定义一致、可被外部同行复核的指标实现，以便我报的数能交叉验证。

#### Acceptance Criteria

1. THE Eval_Framework SHALL 在 `backend/eval/metrics.py` 中提供纯函数 `recall_at_k(relevant, retrieved, k)`、`mrr_at_k(relevant, retrieved, k)`、`ndcg_at_k(relevant, retrieved, k)`、`percentile(values, p)`。
2. THE `recall_at_k(relevant, retrieved, k)` SHALL 定义为 `|set(retrieved[:k]) ∩ relevant| / |relevant|`；WHEN `relevant` 为空集合，THE 该函数 SHALL 返回 `0.0` 而非抛出除零错误。
3. THE `mrr_at_k(relevant, retrieved, k)` SHALL 返回 `retrieved[:k]` 中首个命中位置的倒数（按 1-based 计数）；WHEN 前 k 条中不含任何 relevant 元素，THE 该函数 SHALL 返回 `0.0`。
4. THE `ndcg_at_k(relevant, retrieved, k)` SHALL 以二值相关性（0/1）和 `log2(i+1)`（`i` 从 1 计数）折扣计算 DCG，并以理想排序（所有相关项排在最前）的 DCG 归一化；WHEN `|relevant ∩ retrieved[:k]| == 0`，THE 该函数 SHALL 返回 `0.0`。
5. THE `percentile(values, p)` SHALL 对非空 `values` 返回其第 `p` 分位数；WHEN `values` 为空，THE 该函数 SHALL 返回 `0.0`。
6. THE Eval_Framework SHALL 对每个 `(config, k)` 组合同时上报 `recall`、`mrr`、`ndcg`、`latency_p50`、`latency_p95` 五个字段。
7. THE Test_Suite SHALL 在 `backend/tests/unit/test_metrics.py` 中为以上公式编写例子级用例与属性测试；属性测试至少覆盖 `0.0 <= recall_at_k <= 1.0`、`0.0 <= mrr_at_k <= 1.0`、`0.0 <= ndcg_at_k <= 1.0` 三个取值域不变式。

---

### Requirement 15：Profiles — Lite 与 Full

**User Story：** 作为一名 CI 维护者兼性能优化者，我希望评测框架同时支持零 Docker 的 `lite` profile 与真实 docker-compose 栈的 `full` profile，以便 CI 日常跑 `lite`、基准对比时跑 `full`。

#### Acceptance Criteria

1. THE Eval_Framework SHALL 在 `backend/eval/profiles/lite.py` 中提供 `build_adapters()`，返回全部使用 `backend/tests/fakes/*` 实现的适配器字典（keys：`embedding`、`dense`、`sparse`、`reranker`、`query_rewriter`）。
2. THE Eval_Framework SHALL 在 `backend/eval/profiles/lite.py` 中提供 `install(adapters)`，通过对 `services.retrieval.retriever` 模块属性赋值的方式把生产单例替换为 Fakes。
3. THE Eval_Framework SHALL 在 `backend/eval/profiles/full.py` 中提供 `build_adapters()` 返回生产级适配器（真实 `dense_searcher`、`sparse_searcher`、`embedding_service`、`reranker_service`、`query_rewriter`）。
4. WHEN `--profile lite` 被选中，THE CLI_Runner SHALL NOT 发起任何对 Milvus、PostgreSQL、embedding/reranker HTTP 服务、DeepSeek 的真实 I/O。
5. WHEN `--profile full` 被选中且 docker-compose 栈未就绪（即任一关键依赖探活失败），THE CLI_Runner SHALL 以 exit code `3` 退出并在 stderr 列出未连通的依赖名。
6. WHEN `--profile full` 被选中，THE CLI_Runner SHALL 在入库与评测之间执行一次 warmup 查询，以避免将冷启动延迟计入 p50/p95 指标。

---

### Requirement 16：评测 CLI 与退出码

**User Story：** 作为一名 CI 维护者，我希望评测框架有一个符合 Unix 规范的 `python -m eval.run` 命令行入口，以便我能在 CI pipeline 里按参数矩阵调起评测，并用退出码精确区分错误类型。

#### Acceptance Criteria

1. THE CLI_Runner SHALL 以 `python -m eval.run` 作为入口，并支持参数 `--profile`、`--configs`、`--k`、`--dataset`、`--corpus`、`--kb-id`、`--output-dir`、`--seed`。
2. THE `--profile` SHALL 接受字面量 `lite` 或 `full`；THE `--configs` SHALL 接受逗号分隔的配置名列表；THE `--k` SHALL 接受逗号分隔的正整数列表；THE `--seed` SHALL 接受非负整数。
3. WHEN 未指定 `--profile`，THE CLI_Runner SHALL 默认取 `lite`。
4. WHEN 未指定 `--k`，THE CLI_Runner SHALL 默认取 `[5, 10]`。
5. WHEN 未指定 `--output-dir`，THE CLI_Runner SHALL 将报告写入 `backend/eval/reports/`。
6. WHEN `--help` 被请求，THE CLI_Runner SHALL 输出用法说明并以 exit code `0` 退出。
7. WHEN 运行成功并成功写出报告文件，THE CLI_Runner SHALL 以 exit code `0` 退出。
8. IF 参数解析失败或数据集/语料校验失败，THEN THE CLI_Runner SHALL 以 exit code `2` 退出。
9. IF 运行期发生未预期的运行时错误（例如 Milvus 连接超时、embedding HTTP 非 2xx），THEN THE CLI_Runner SHALL 以 exit code `3` 退出并在 stderr 打印错误摘要。

---

### Requirement 17：Markdown 报告格式

**User Story：** 作为一名读者（或招聘/面试官），我希望通过 README 链接直接看到一份结构清晰的评测报告，以便不用自己跑代码也能评估 RAGForce 的检索质量。

#### Acceptance Criteria

1. THE Report_Generator SHALL 输出一份 Markdown 文件，文件名格式 SHALL 为 `YYYY-MM-DD-<profile>.md`，写入 `--output-dir` 指定目录（默认 `backend/eval/reports/`）。
2. THE 报告 SHALL 在开头包含元数据块，至少列出：Profile 名、数据集路径、数据集条目数、参与配置集合、k 值、随机种子、wall time。
3. THE 报告 SHALL 为每个 `k` 输出一张 **Summary 矩阵表**，列至少包含 `Config`、`Recall@k`、`MRR@k`、`nDCG@k`、`p50 ms`、`p95 ms`；每个数值 SHALL 保留不超过 4 位小数。
4. THE 报告 SHALL 包含 **Per-query breakdown** 段落，对前 10 条 query 输出各配置下的命中情况（`✓` / `✗`）。
5. THE 报告 SHALL 在末尾包含 **How to reproduce** 段落，给出可被直接复制运行的命令行（含 `--profile`、`--configs`、`--k`、`--seed`）与环境准备步骤。
6. THE 报告 SHALL 只包含指标、配置名和脱敏后的 query 文本，SHALL NOT 包含任何 API key、secret、内网主机名或 IP。
7. WHERE `README.md` 引用报告，THE Report_Generator SHALL 保证生成的 Markdown 使用相对路径的锚点与表格，能被 GitHub 渲染器正确显示。

---

### Requirement 18：评测可复现性

**User Story：** 作为一名性能优化者，我希望在同一 `--seed` 下两次运行 `lite` profile 的评测得到完全相同的指标，以便回归可验证、结果可归因。

#### Acceptance Criteria

1. THE CLI_Runner SHALL 接受 `--seed` 参数并在启动时将其同时设置为 Python `random.seed`、`numpy.random.seed`（若已安装）、`hypothesis` profile 的全局种子。
2. WHEN 在 `lite` profile 下以相同的 `--seed`、相同的数据集、相同的 `--configs` 与 `--k` 两次运行 CLI_Runner，THE 两次报告的所有指标数值（Recall@k、MRR@k、nDCG@k）SHALL 完全一致。
3. THE Fakes（`FakeEmbeddingService`、`InMemoryDenseSearcher`、`InMemorySparseSearcher`、`FakeRerankerService`、`FakeQueryRewriter`）SHALL 对相同输入返回完全相同的输出（确定性）。
4. THE Eval_Framework SHALL 在 ingest 与检索阶段按稳定顺序（例如按 `qid` 升序、按 chunk `index` 升序）迭代，以避免字典遍历顺序导致输出漂移。
5. WHEN 未指定 `--seed`，THE CLI_Runner SHALL 默认使用 `42` 并在报告元数据中回显。
6. THE 报告文件元数据块 SHALL 包含 `seed` 字段，其值 SHALL 与启动参数一致。

---

### Requirement 19：不修改生产代码的测试注入方式

**User Story：** 作为一名开发者，我希望测试与评测框架的 Fakes 注入不依赖对生产代码的侵入式改造，以便本特性可以独立开发、回滚与维护。

#### Acceptance Criteria

1. THE Test_Suite SHALL 通过 `monkeypatch.setattr` 在 `services.retrieval.retriever` 模块上替换 `dense_searcher`、`sparse_searcher`、`reranker_service`、`query_rewriter`、`embedding_service` 五个模块级变量。
2. THE Test_Suite SHALL 通过 `app.dependency_overrides[core.database.get_db] = ...` 覆写数据库会话依赖，并在 Fixture 拆解阶段 SHALL 调用 `app.dependency_overrides.clear()` 以复原。
3. THE Eval_Framework 的 `profiles/lite.py install()` SHALL 通过对 `services.retrieval.retriever` 模块属性直接赋值完成 Fakes 替换。
4. THE 本特性 SHALL NOT 修改 `backend/src/services/retrieval/retriever.py`、`backend/src/services/ingestion/chunker.py`、`backend/src/services/retrieval/fusion.py`、`backend/src/services/retrieval/reranker.py`、`backend/src/services/ingestion/embedder.py`、`backend/src/services/retrieval/query_rewriter.py`、`backend/src/services/generation/deepseek_chat.py` 这七个生产文件的业务逻辑（允许的变更仅限：新增 docstring、新增 `typing.Protocol` 注解、不改变运行时行为的注释）。
5. IF 生产代码的导入结构被重构（例如去掉模块级单例改为工厂函数），THEN THE Test_Suite SHALL 以明确的 `ImportError` 或 `AttributeError` 失败，而非悄悄使用真实单例。
6. THE 本特性 SHALL NOT 在生产依赖列表（`[project].dependencies`）中新增任何测试专用库；所有新增依赖 SHALL 仅进入 `[project.optional-dependencies].dev`。

---

### Requirement 20：Windows 兼容性

**User Story：** 作为一名使用 Windows 的开发者，我希望所有单元、集成、API、属性测试与 `python -m eval.run --profile lite` 在 Windows 上能直接运行，以便不必切换到 WSL。

#### Acceptance Criteria

1. WHERE `sys.platform == "win32"`，THE Test_Suite SHALL 在 `conftest.py` 启动阶段调用 `asyncio.set_event_loop_policy(WindowsSelectorEventLoopPolicy())` 以替换默认的 ProactorEventLoop。
2. WHERE `sys.platform == "win32"`，THE Eval_Framework SHALL 在 `eval/run.py` 的入口同样设置 `WindowsSelectorEventLoopPolicy`。
3. WHEN 在 Windows 上执行 `pytest -m "not docker and not slow"`，THE Test_Suite SHALL 成功完成，SHALL NOT 出现 `NotImplementedError: set_wakeup_fd only works in main thread`、`ProactorEventLoop` 相关的 `aiosqlite`/`httpx` 异常或事件循环关闭顺序异常。
4. WHEN 在 Windows 上执行 `python -m eval.run --profile lite`，THE CLI_Runner SHALL 成功写出报告文件，SHALL NOT 因路径分隔符差异而失败。
5. THE Test_Suite 与 Eval_Framework 在读写报告与 fixture 文件时 SHALL 统一使用 `pathlib.Path` 或以 `/` 为分隔符的相对路径，SHALL NOT 硬编码 `\\`。
6. IF `aiosqlite` 在 Windows 上出现事件循环关闭相关的 warning 或 error，THEN THE Test_Suite SHALL 通过 session 级 event loop fixture 保证同一循环贯穿整个测试会话，以抑制此类异常。
