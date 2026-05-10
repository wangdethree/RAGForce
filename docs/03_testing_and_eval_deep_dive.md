# 测试与评测框架深度讲解

> 对应 spec：`.kiro/specs/testing-and-eval-framework/`。
> 对应实现：`backend/tests/` + `backend/eval/`。

## 这份文档讲什么

讲**为什么这么设计**，而不是讲"这里是类定义"。如果你想看"有哪些类/函数"，读 `requirements.md` 和 `design.md`。

三个部分：

- **第一部分**：核心测试套件（`backend/tests/`）——Fakes、Fixtures、PBT、单元、集成、API 契约
- **第二部分**：检索质量评测框架（`backend/eval/`）——数据集、Profile、Runner、Report
- **第三部分**：关键设计权衡与常见坑

---

# 第一部分：核心测试套件

## 1. 为什么要有这个框架

生产 RAG 管线有两类 bug：

1. **功能正确性**：切分丢字、RRF 分数算错、重排引入了新候选……这些靠 assertEqual 查不全
2. **基础设施正确性**：Milvus 没连上、PG 超时、DeepSeek API 限流……这些不应阻塞"跑单元测试"

所以设计了一套"**双轨**"：

- **单元 / 集成测试**：全部走内存 Fakes，零 Docker 依赖，30 秒跑完
- **评测框架**：lite profile 走 Fakes（快速回归），full profile 走真实栈（质量基线）

同一套代码支持两条路径，关键在于**模块级单例 + 运行时属性替换**。

## 2. Fakes：为什么不用 MagicMock

常见做法是 `unittest.mock.MagicMock()`：

```python
mock_dense = MagicMock()
mock_dense.search.return_value = [{"chunk_id": "a", "score": 0.9}]
```

问题：

- **没有真实语义**。返回的永远是硬编码 list，不会随 query 变化
- **容易测 false positive**：测试在跑，但没在测任何真东西
- **Property-Based Testing 时根本用不了**：Hypothesis 生成随机 query，MagicMock 永远返回同一个死值

所以 `tests/fakes/` 下写的是**有真实语义的轻量实现**：

| Fake | 真实语义 |
|---|---|
| `FakeEmbeddingService` | 基于 2/3-char shingle + SHA256 哈希的确定性 1024 维向量 |
| `InMemoryDenseSearcher` | 字典存 chunk，cosine 相似度排序 top_k |
| `InMemorySparseSearcher` | 中英混排分词 + Counter 词元重叠打分 |
| `FakeRerankerService` | 用 sparse searcher 的分词函数对候选重打分 |
| `FakeQueryRewriter` | 默认恒等变换，可构造参数注入额外变体 |
| `FakeDeepSeekChat` | 拼装罐头 ChatResponse，永不发网络请求 |

确定性是关键——同样的输入永远产生同样的输出，让 PBT 可复现。

## 3. Fixtures：三层架构

`conftest.py` 严格分三层，每层职责单一：

```
┌──────────────────────────────────────────────────┐
│ 基础块（3.3）                                     │
│   - Windows 事件循环策略切换                        │
│   - 环境变量兜底                                   │
│   - session 级 event_loop                         │
├──────────────────────────────────────────────────┤
│ 数据库块（3.4）                                    │
│   - async_engine (session): in-mem SQLite + StaticPool │
│   - db_session (function): AsyncSession            │
├──────────────────────────────────────────────────┤
│ FastAPI 块（3.5）                                  │
│   - app: 带 dependency_overrides 的 FastAPI 实例   │
│   - async_client: httpx.AsyncClient + ASGITransport│
├──────────────────────────────────────────────────┤
│ Fakes 注入块（3.6）                                │
│   - 6 个单体 fake_* fixtures                        │
│   - wired_pipeline: 组合 5 个检索 Fakes             │
│   - seeded_kb: 预填充 5 条样例 chunk                │
└──────────────────────────────────────────────────┘
```

### 3.1 为什么需要 StaticPool

SQLite `:memory:` 的库是**连接级**的——每个 connection 拿到一个独立的空库。如果用默认 pool，不同 session 看到的是不同内存库，FastAPI 的 dependency_override 和测试代码各操作一边，互相看不见。

`StaticPool` 强制整个 engine 复用同一条底层连接，所有 session 共享同一个内存库。

### 3.2 为什么 `expire_on_commit=False`

SQLAlchemy 默认 commit 后把 ORM 实例标记为 "expired"，下次访问字段触发额外 SELECT。在 async 场景下没有 greenlet 支撑 → 抛 `MissingGreenlet`。

设为 `False` 让 commit 后实例仍可直接访问字段（生产 `core/database.py` 也这么配的，保持测试与生产行为一致）。

### 3.3 为什么 `httpx.AsyncClient + ASGITransport`

传统做法是启动 uvicorn → requests 打 localhost:8000，慢又需要端口。

ASGITransport 让 httpx **直接与 FastAPI ASGI app 对话**，请求不出进程：

- 无需端口、无冲突
- 微秒级延迟，整套 API 契约测试 10 秒内完成
- Windows 下规避 Proactor 事件循环的 socket 兼容问题

### 3.4 `dependency_overrides.clear()` 为什么要在 finally 里

FastAPI 的 `dependency_overrides` 是**模块级字典**。如果上一个测试往里放了覆盖后没清掉，下一个测试会继承这个覆盖——然后由于 session 已关闭，会抛"Session is closed"或"MissingGreenlet"。

在 `yield` 之后、`finally` 里 `clear()` 是兜底——即使测试中途抛异常也能还原。

## 4. Property-Based Testing（PBT）

### 4.1 思路：例子测试 vs 性质测试

例子测试（传统）：

```python
def test_rrf_two_paths():
    out = rr_fusion.fuse(dense=[A, B], sparse=[B, A])
    assert out[0]["chunk_id"] == "B"  # 因为 B 在两路都排第 1，分最高
```

这只证明了"这一个例子对"。

性质测试：

```python
@given(dense=records_strategy(), sparse=records_strategy())
def test_rrf_output_is_subset(dense, sparse):
    out = rr_fusion.fuse(dense, sparse)
    chunk_ids_in = {r["chunk_id"] for r in dense} | {r["chunk_id"] for r in sparse}
    chunk_ids_out = {r["chunk_id"] for r in out}
    assert chunk_ids_out.issubset(chunk_ids_in)
```

Hypothesis 会生成 **100+ 组随机输入**跑这条断言，包括你想不到的边界（空 list、同一 chunk 出现多次、分数全 0、超长 chunk_id……）。

### 4.2 Hypothesis 的 shrinking 是关键能力

当找到反例时，Hypothesis 不会把"200 条 chunk 组成的复杂输入"直接甩给你，而是**不断缩小反例**，直到得到一个最小反例：

```
Falsifying example: dense=[], sparse=[{"chunk_id": "a", "score": 0.5}]
```

"两路之一为空时出错"——立刻能看出是边界处理有问题。

### 4.3 本项目的 17 条 property

都在 `design.md` 的"Correctness Properties"段落列出来了。按组件分：

| 组件 | 属性编号 | 数量 |
|---|---|---|
| RRF 融合 | P1-P6 | 6 |
| Retriever 管线 | P7-P10, P15 | 5 |
| Chunker | P11-P14 | 4 |
| 评测指标 | P16 | 1 |
| 评测可复现性 | P17 | 1 |

每条都对应 `tasks.md` 里一个可选测试子任务（以 `*` 标记）。新人推荐先从 P1（"RRF 输出是输入并集的子集"）开始写，概念最简单。

### 4.4 max_examples 的权衡

- 默认值 100（Hypothesis 默认）已足够发现绝大多数 bug
- 评测可复现性（P17）只设 20，因为每次执行要跑一轮完整评测，太贵
- 在 CI 上可以用 `@settings(max_examples=200)` 局部加码

## 5. Fakes 注入机制：monkeypatch vs dependency_override

两个关键注入点：

1. **生产代码的模块级单例**（如 `services.retrieval.retriever.dense_searcher`）
   - 用 `monkeypatch.setattr` 替换
   - pytest 在用例结束时自动还原
2. **FastAPI 路由的依赖**（如 `core.database.get_db`）
   - 用 `app.dependency_overrides[get_db] = _override` 替换
   - 在 `finally` 里 `app.dependency_overrides.clear()`

**为什么要两种**：

- 业务逻辑里的单例是普通 Python 对象，只能用 `setattr`
- FastAPI Depends 走的是特殊 DI 机制，必须通过 `dependency_overrides`

---

# 第二部分：评测框架

## 1. 为什么自己写而不是用现成框架

候选：RAGAS、TruLens、LangSmith Eval……

这些框架都有一个共性：**耦合在一个特定 LLM 栈上**（LangChain / LlamaIndex）。本项目的生产管线是手写的 FastAPI + 自研 Retriever，硬塞不进去。

自己写的价值：

- **直接复用生产代码**：`eval/ingest.py` 调用的就是生产 `DocumentChunker`
- **同一个 runner 既能 lite 又能 full**：通过 profile 切换 adapters
- **可复现性可控**：固定 seed 就能保证两次 lite 运行指标完全一致（Property 17）

## 2. 数据集：5 篇中文语料 + 25 条 QA

`backend/eval/datasets/` 目录：

```
corpus/
  ├── doc_01_rag.md
  ├── doc_02_milvus.md
  ├── doc_03_bge.md
  ├── doc_04_rrf.md
  └── doc_05_deepseek.md
qa_zh.jsonl                 # 25 条 QA
```

**JSONL 字段契约**（`dataset.py::QAEntry`）：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `qid` | ✓ | str | 稳定唯一 ID（`q001`..`q025`） |
| `query` | ✓ | str | 中文查询（strip 后非空） |
| `relevant_doc_ids` | ✓ | list[str] | corpus basename（去扩展名） |
| `relevant_chunk_ids` | - | list[str] / null | 精确 chunk 级标注 |
| `answer` | - | str | 参考答案（v1 不参与评分） |
| `difficulty` | - | easy/medium/hard | 分层用 |

**难度分层**：easy=12（直接问定义）、medium=8（细节/对比）、hard=5（跨文档综合）。这让评测报告能分层看：如果只在 hard 题上下降，就知道是推理能力问题，不是检索能力问题。

## 3. Runner 编排：`run.py`

主流程（精简）：

```python
async def run_eval(run_config: RunConfig) -> dict:
    wall_start = time.time()

    # 1) 固定随机种子 → 可复现性基础
    random.seed(run_config.seed)
    numpy.random.seed(run_config.seed)  # 如已安装

    # 2) 装配 profile adapters
    profile_mod = importlib.import_module(f"eval.profiles.{run_config.profile}")
    adapters = profile_mod.build_adapters()
    profile_mod.install(adapters)

    # 3) Full profile 独有：健康探活
    if run_config.profile == "full":
        down = await profile_mod.health_check(adapters)
        if down:
            raise _HealthCheckError(down)  # runner 映射为 exit 3

    # 4) 入库 corpus → 得到 doc_name -> chunk_ids 映射
    doc_map = await ingest_corpus(
        run_config.corpus_path, run_config.kb_id,
        embedder=adapters["embedding"],
        dense_store=adapters["dense"],
        sparse_store=adapters["sparse"],
    )

    # 5) 加载 + 校验 QA 数据集
    entries = load_and_validate(run_config.dataset_path, run_config.corpus_path)

    # 6) Full profile 独有：warmup 查询（不计入 p50/p95）
    if run_config.profile == "full":
        await retriever.retrieve(kb_id=..., query=entries[0].query, top_k=5)

    # 7) 双层循环 config × k
    for cfg in run_config.configs:
        for k in run_config.k_values:
            for qe in entries:
                result = await retriever.retrieve(kb_id=..., query=qe.query, top_k=k, ...)
                retrieved_ids = [r.chunk_id for r in result.results]
                relevant = _resolve_relevant(qe, doc_map)
                # 累加 recall / mrr / ndcg / latency_ms
            # 聚合 (cfg, k) 的平均指标 + 延迟百分位

    # 8) 渲染 Markdown 报告
    report_path = report.render(run_config=run_config, metrics=..., per_query=..., ...)

    return {"report_path": report_path, "wall_time_s": ..., "metrics": ..., "per_query": ...}
```

**exit code 契约**：

- `0` — 成功
- `2` — 参数/数据集错误（未知 config、JSONL 违约、corpus 缺文件）
- `3` — 运行期错误（健康探活失败、retrieve 抛异常、HTTP 非 2xx）
- `130` — Ctrl+C（Python 默认）

## 4. 评测指标：`metrics.py`

四个纯函数。关键点：

| 指标 | 公式 | 边界 |
|---|---|---|
| `recall_at_k` | $\|R \cap \text{top}_k\| / \|R\|$ | 空 relevant → 0.0 |
| `mrr_at_k` | 前 k 条首次命中位置的倒数 | 未命中 → 0.0 |
| `ndcg_at_k` | 二值相关性 + $\log_2(i+1)$ 折扣，按理想 DCG 归一化 | 0 命中 → 0.0 |
| `percentile` | 线性插值 | 空输入 → 0.0 |

**为什么 Recall@5 通常低于 Recall@10**：分子变大的速度慢于分母（前 5 条里能命中的相关文档有上限）——但**这只在 relevant_docs 数量 > 5 时才明显**。如果 relevant 只有 1-2 条，Recall@5 ≈ Recall@10 很正常。

**为什么 nDCG@5 在我们的报告里反而高于 nDCG@10**：nDCG 的分母是"理想 DCG"——当 relevant 只有 1 个、你又正好排在第 1 位，nDCG@5 和 nDCG@10 都是 1.0；但如果 relevant 有 3 个，你在 top 5 命中 2 个、top 10 命中 3 个，前者 nDCG 可能反而更高（因为 top 5 的折扣权重给得更重）。这不是 bug。

## 5. 报告：`report.py`

输出到 `backend/eval/reports/YYYY-MM-DD-<profile>.md`，同日同 profile 覆盖写入。

**四段结构**：

1. **元数据块**：profile / dataset_path / entries_count / configs / k / seed / wall_time / started_at
2. **Summary 矩阵**：每个 k 一张表，列固定 `Config | Recall@k | MRR@k | nDCG@k | p50 ms | p95 ms`
3. **逐条命中**：前 10 条 query 在各 config 下的 ✓/✗
4. **如何复现**：可复制的命令行 + 环境准备

**脱敏**：所有路径走 `_safe_relative_path()`，绝对路径裁成相对或退回 basename，不输出盘符、内网主机、API key。

## 6. Lite vs Full Profile 的本质差异

| 维度 | Lite | Full |
|---|---|---|
| 外部依赖 | 零 | Milvus + PG + BGE-M3 + BGE-Reranker + DeepSeek |
| 执行时间 | 1-3 秒 | 10-60 秒 |
| adapters 来源 | `tests/fakes/` | 生产单例 |
| `install()` 行为 | 覆盖 6 个模块级变量 | 空函数（生产接线已 done） |
| warmup | 不需要 | 做一次不计时的查询 |
| health_check | 不需要 | 4 类依赖逐一探活 |
| 用途 | 功能回归、CI 门禁 | 质量基线、版本对比 |

**同一份 `retriever.retrieve()` 代码两种 profile 都跑**——这正是"零修改生产代码"的架构价值。

---

# 第三部分：关键设计权衡与常见坑

## 权衡 1：为什么不用 `tox` / `poetry`

用 `pip install -e ".[dev]"` + `pyproject.toml.optional-dependencies.dev`。原因：

- 新人学习曲线更低（不用再学一套工具）
- 与现有生产 Dockerfile 一致
- `pyproject.toml.tool.pytest.ini_options` 已经能组织测试，不需要再套一层 tox

## 权衡 2：为什么选 SQLite 做测试 DB 而不是 testcontainers PG

- 启动时间：SQLite 内存 <10ms，PG 容器 3-10 秒
- 零 Docker 依赖是本项目的硬约束（Req 9.5）
- 唯一缺点：PG 特有的 `tsvector` / JSON 操作在 SQLite 下跑不了——所以涉及这些的测试走 integration 走真实 PG（而不是 unit 走 SQLite）

## 权衡 3：Property 17（评测可复现）为什么 `max_examples=20` 还加 `@slow`

每次执行要跑完整评测（ingest + retrieve × N + metrics），耗时 1-2 秒。100 次就是 100-200 秒，在 CI 上挤占预算。

折中：20 次 + `@pytest.mark.slow` + 默认跳过。发版前手动触发：

```bash
pytest -m "property and slow"
```

## 坑 1：`pytest-asyncio` 的 `asyncio_default_fixture_loop_scope`

新版 pytest-asyncio 会警告 `asyncio_default_fixture_loop_scope` 未设置。在 `pyproject.toml`：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

## 坑 2：Windows 事件循环必须在 import 期切换

```python
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

这行必须写在 `conftest.py` 顶层（不是 fixture 内部）。某些 pytest 插件在 conftest 加载时就会触发事件循环初始化，推迟到 fixture 内就晚了。

## 坑 3：生产 `retriever.py` 的 `from ... import ...` 绑定

生产代码里是 `from services.retrieval.dense_searcher import dense_searcher`——这会把对方模块的**当前属性值拷贝**到 retriever 的命名空间。所以 lite profile 的 `install()` 必须**在 retriever 模块上**重新赋值，不能只改源头模块：

```python
# ✅ 对的
retriever_mod.dense_searcher = fake_dense

# ❌ 错的（已经被 import 绑定过了）
dense_searcher_mod.dense_searcher = fake_dense
```

## 坑 4：相对路径 vs CWD

Runner 的 CLI 参数里 `--dataset eval/datasets/qa_zh.jsonl` 是相对路径，假定 CWD 是 `backend/`。如果从仓库根跑就会找不到文件。修法：

```python
# 测试里用绝对路径推导
_REPO_ROOT = Path(__file__).resolve().parents[3]
_DATASET_PATH = _REPO_ROOT / "backend" / "eval" / "datasets" / "qa_zh.jsonl"
```

## 坑 5：`--exclude` 参数形式

HuggingFace `hf download` 的 `--exclude` **每个 glob 都要前缀 `--exclude`**：

```bash
# ✅ 对
hf download ... --exclude "onnx/*" --exclude "imgs/*"

# ❌ 错（后两个会被当成"要下载的文件名"）
hf download ... --exclude "onnx/*" "imgs/*"
```

---

# 推荐的阅读/动手顺序（给已经看完架构的人）

1. **读 `design.md`**（30 min）：理解 17 条 property 是怎么来的
2. **读 `tests/fakes/embedding.py`**（10 min）：体会"确定性 Fake"怎么写
3. **读 `tests/conftest.py`**（20 min）：理解四层 fixture 架构
4. **跑一遍烟测**（5 min）：`pytest tests/integration/test_eval_smoke.py -v`
5. **读 `eval/run.py`**（20 min）：理解 runner 编排
6. **跑一次 lite 评测**（5 min），打开生成的 Markdown 报告
7. **从 `tasks.md` 里挑一条 `*` 标记的 property 任务**，自己写一遍

完成这 7 步后，你就具备独立扩展这套框架的能力了。

## 一句话总结

**这套框架本质上是把"RAG 质量工程"从手动测试升级成可复现的自动化基线**——让"稠密 vs 混合 vs rerank vs 完整管线"的对比从主观感受变成数字证据，让"某次代码改动是否回归"从 ad hoc 排查变成 CI 上的明确断言。
