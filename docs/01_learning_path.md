# RAGForce 学习路线图

> 一份按周划分的学习计划，从"能把项目跑起来"到"能独立扩展检索管线和评测框架"。

## 总览

RAGForce 是一个**企业级 RAG（检索增强生成）平台**。它把一条完整的 Advanced RAG 管线工程化：文档摄入、混合检索、重排序、上下文组装、带引用的流式生成、可观测性、评测闭环。

学完这个仓库，你会获得三类能力：

1. **工程能力**：FastAPI 全链路异步 / docker-compose 13 服务编排 / SQLAlchemy 2.x async ORM / Alembic 迁移
2. **检索系统能力**：BGE-M3 稠密向量 + PostgreSQL 全文 BM25 稀疏检索 + RRF 融合 + BGE-Reranker-v2-m3 交叉编码器重排 + 基于 DeepSeek 的查询改写
3. **质量保障能力**：Property-Based Testing（Hypothesis）/ 内存 Fakes 替身 / pytest + httpx ASGI 进程内测试 / 可复现的检索质量评测框架

---

## 前置要求

- Python 3.11+，基本会读 async/await
- 读过一点 FastAPI 或 Flask 教程
- 知道向量检索、embedding 是什么（不必深入理论）
- Docker Desktop 会用

不熟悉也没关系，第 1 周的任务就是把它补齐。

---

## 5 周学习计划

### 第 1 周 · 把项目跑起来 + 建立心智模型

**目标**：能在本机跑完整栈；能回答"从 HTTP 请求到 DeepSeek 回复，数据流经了哪些模块"。

**任务**：

1. 按根 `README.md` 启动 docker compose 全栈，访问前端、Swagger、Jaeger、Grafana
2. 跳过模型下载，用 **lite profile** 先跑一次评测：
   ```powershell
   cd backend
   d:\python_code\ragforce\.venv\Scripts\python.exe -m eval.run --profile lite --configs dense_only,hybrid --k 5
   ```
   打开 `backend/eval/reports/YYYY-MM-DD-lite.md`，看看评测报告长什么样
3. 用 Swagger 调 `POST /api/v1/knowledge-bases` 创建一个 KB，再调 `POST /api/v1/retrieval`（此时返回空，因为还没入库），感受请求-响应循环
4. 画一张**一页纸架构图**（纸上手画也行）：前端 → FastAPI → Retriever → Dense+Sparse+Rerank → DeepSeek → 流式回复，标出每个框对应的 Docker 容器

**产出检查**：能指着你的架构图给别人讲清楚"为什么需要 PostgreSQL 又需要 Milvus"。

**时间估计**：6-10 小时。

---

### 第 2 周 · 读完检索管线源码

**目标**：理解 `backend/src/services/retrieval/` 下每个文件的职责与协作关系。

**重点阅读顺序**（由浅入深）：

| 文件 | 核心概念 |
|---|---|
| `services/ingestion/chunker.py` | 段落切分的边界启发式 |
| `services/retrieval/fusion.py` | RRF 的 `1/(k+rank)` 公式 |
| `services/retrieval/query_rewriter.py` | DeepSeek 如何生成多角度查询变体 |
| `services/retrieval/dense_searcher.py` | Milvus HNSW 索引查询 |
| `services/retrieval/sparse_searcher.py` | PostgreSQL `tsvector` 查询 |
| `services/retrieval/reranker.py` | Cross-Encoder HTTP 调用 |
| `services/retrieval/retriever.py` | **管线编排**（所有组件串起来的地方） |

每读完一个文件，在笔记里写一行"它的输入、输出、副作用"。

**练习**：

1. 在 `retriever.py` 里给自己加几行 `print`，跟踪 `(use_hybrid=True, use_rerank=True)` 时候选集大小的变化
2. 把 `fusion.py` 的 `k` 从 60 改成 10 再改成 200，分别跑一次 lite 评测，对比 nDCG@5 的变化，直观体会 `k` 的"平滑"作用

**配套文档**：细读 `docs/02_architecture_walkthrough.md` 的"检索管线"一节。

**时间估计**：8-12 小时。

---

### 第 3 周 · 文档摄入与数据存储

**目标**：理解文档从上传到可检索要经过哪些步骤。

**重点阅读**：

- `services/ingestion/parser.py` — PDF / Word 解析
- `services/ingestion/chunker.py` — 切分（第 2 周已读）
- `services/ingestion/embedder.py` — 批量 embedding（BGE-M3 HTTP 客户端）
- `services/ingestion/indexer.py` — 写 Milvus + PostgreSQL
- `worker/doc_processing.py` — Celery 异步任务编排

**数据层**：

- `models/` — SQLAlchemy ORM 模型定义
- `migrations/versions/001_initial_tables.py` — 初始 schema
- `core/database.py` — async engine 与 session 管理

**练习**：

1. 在 Swagger 上传一份 PDF，用 `docker compose logs -f backend` 跟踪整条日志
2. 用 `docker compose exec postgres psql -U ragforce -d ragforce` 直接查 `documents`、`document_chunks` 表，看一条 chunk 长什么样
3. 用 Milvus Attu（或 pymilvus CLI）看看向量是怎么存的

**时间估计**：6-10 小时。

---

### 第 4 周 · 测试与评测框架（本次交付重点）

**目标**：读懂 `backend/tests/` 和 `backend/eval/` 全部代码，会扩展。

**按顺序阅读**：

1. `.kiro/specs/testing-and-eval-framework/requirements.md` — 20 条 EARS 需求
2. `.kiro/specs/testing-and-eval-framework/design.md` — HLD + LLD + 17 条 Correctness Property
3. `backend/tests/fakes/` — 6 个 Fake 适配器，每个 100-150 行，带详细中文注释
4. `backend/tests/conftest.py` — fixture 层（事件循环 / SQLite / FastAPI / Fakes 注入）
5. `backend/tests/properties/strategies.py` — Hypothesis 策略
6. `backend/eval/` 全部 — 评测框架 runner

**练习**：

1. 跑一遍烟测：
   ```powershell
   cd backend
   d:\python_code\ragforce\.venv\Scripts\python.exe -m pytest tests/integration/test_eval_smoke.py -v -m integration --no-cov
   ```
2. **自己写一条 RRF property**。提示：`design.md` 里有 Property 1-6，挑一条 `tasks.md` 里还没打勾的（如 Property 1：RRF 输出是输入并集的子集），在 `tests/properties/test_rrf_properties.py` 里落地
3. 给 `qa_zh.jsonl` 新增 3 条跨文档 QA，重跑评测看 nDCG 变化

**配套文档**：`docs/03_testing_and_eval_deep_dive.md` 一定要读，里面解释了 Fakes 注入、monkeypatch、Hypothesis 收缩（shrinking）等关键机制。

**时间估计**：10-15 小时。

---

### 第 5 周 · 扩展与贡献

**目标**：选择一个方向，向仓库提一个有价值的 PR。

**候选方向**（难度递增）：

| 方向 | 内容 | 难度 |
|---|---|---|
| 新增一条 property 测试 | 从 `tasks.md` 的 `* 6.2-6.7 / 8.1-8.5 / 7.5-7.9 / 11.3 / 14.2` 里挑一条落地 | ⭐⭐ |
| 新增一个 RetrievalConfig | 在 `eval/config.py` 的 `PRESET_CONFIGS` 里加一条（如 `rerank_only`），跑对比评测 | ⭐⭐ |
| 实现查询改写的 fallback | DeepSeek 超时/失败时回退到单一 query（查 `query_rewriter.py`） | ⭐⭐⭐ |
| 前端改进 | 在 chat 页面展示 citation 的分数分布条形图 | ⭐⭐⭐ |
| 新增评测指标 | 在 `eval/metrics.py` 加 `map_at_k`（mean average precision），并让 `report.py` 渲染 | ⭐⭐⭐⭐ |

**时间估计**：10-20 小时。

---

## 学习资源推荐

### 必读论文（按项目相关度）

- **RRF**: Cormack et al. 2009, *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods*
- **BGE-M3**: Chen et al. 2024, *BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity*
- **Cross-Encoder 重排**: Nogueira & Cho 2019, *Passage Re-ranking with BERT*
- **Advanced RAG 综述**: Gao et al. 2023, *Retrieval-Augmented Generation for Large Language Models: A Survey*

### 工具文档

- [FastAPI 官方教程](https://fastapi.tiangolo.com/)（异步章节必看）
- [SQLAlchemy 2.x async ORM](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Hypothesis 官方教程](https://hypothesis.readthedocs.io/en/latest/tutorial.html)（第 4 周核心）
- [Milvus 官方文档的 HNSW / Hybrid Search 章节](https://milvus.io/docs)

### 深入阅读

- [PBT 入门博客 - "An Introduction to Property-Based Testing" (F# for Fun and Profit)](https://fsharpforfunandprofit.com/posts/property-based-testing/)
- [httpx ASGI 测试指南](https://www.python-httpx.org/async/#calling-into-python-web-apps)

---

## 常见学习陷阱

1. **急着读 `retriever.py` 之前，先把 `fusion.py` 和 `query_rewriter.py` 读完**。前者是编排者，后者才是真逻辑。
2. **不要跳过 lite profile**。用 Fakes 跑通再上真实模型，能把"功能逻辑问题"和"基础设施问题"解耦开，调试效率翻几倍。
3. **Property-Based Testing 的第一道坎是"怎么想属性"**，不是怎么写代码。遇到卡壳就回到 `design.md`，那里列了 17 条现成的属性。
4. **评测报告的指标不等于排名**。Recall@k / MRR@k / nDCG@k 各有适用场景，看不懂别瞎调，`eval/README.md` 里写了每个指标的数学定义。

---

## 里程碑自检

- [ ] Week 1 完成：能用一张纸讲清楚 RAG 请求的完整数据流
- [ ] Week 2 完成：能徒手画出 `Retriever.retrieve()` 的四阶段流程图
- [ ] Week 3 完成：能解释"为什么 chunk 要有 overlap"和"为什么稀疏稠密都需要"
- [ ] Week 4 完成：能独立写出一条新的 RRF property 并跑过
- [ ] Week 5 完成：提了一个 PR 并通过 lite 评测回归

祝学习顺利。如果中途有卡壳点，在文档里做笔记，下一轮迭代可以贡献回 `docs/`。
