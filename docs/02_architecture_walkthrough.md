# RAGForce 架构与代码详解

> 跟着源码读一遍，建立"看到一个请求 → 能脑内追踪它流经哪些模块"的能力。

## 阅读方式

这份文档按**从外到内、从调用者到被调用者**的顺序组织。读每一节时，请同时打开对应的源码文件一起看，文档只讲"为什么这么设计"与"关键细节"，不重复源码。

---

## 一、总体分层

```
frontend (React)
     │  HTTP
     ▼
nginx  ────→  FastAPI (backend container)
                │
                ├── core/          配置 / 日志 / 异常 / DB session
                ├── middleware/    审计日志 / Prometheus 指标
                ├── api/v1/        路由层（thin）
                ├── schemas/       Pydantic request/response
                ├── models/        SQLAlchemy ORM
                ├── services/      业务层（厚）
                │   ├── ingestion/   解析 / 切分 / 向量化 / 索引
                │   ├── retrieval/   稠密 / 稀疏 / RRF / 重排 / 查询改写 / 编排
                │   └── generation/  DeepSeek Chat
                └── worker/        Celery 异步任务
```

**分层的两条黄金规则**：

1. **api/v1 永远薄**。路由只做三件事：拆参、调 service、包响应。没有业务分支逻辑。
2. **services 永远深**。所有业务判断、组件编排、容错降级都在这里。

---

## 二、请求入口：`main.py`

文件：`backend/src/main.py`（~60 行，直接读完）

关键点：

- **模块级副作用**：`from models import KnowledgeBase, ...` 不是"用"这些 import，而是**强制触发 ORM 类注册到 `Base.metadata`**。Alembic autogenerate 能识别这些模型全靠这一步。
- **中间件顺序**：`MetricsMiddleware` → `AuditMiddleware` → `CORSMiddleware`。FastAPI 的 `add_middleware` 是**倒序叠加**的，所以实际执行栈是：CORS 最外层 → Audit → Metrics → 业务。
- **`lifespan` 是空的**：这是为 1.0 预留的，以后如果要在启动时预热 Milvus 连接或 warmup BGE 就往这里放。

---

## 三、配置层：`core/config.py`

使用 `pydantic-settings`，所有字段都有类型和默认值。

关键 idiom：

```python
@property
def database_url(self) -> str:
    return (
        f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
        f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
    )
```

把"分散的原子配置"组合成一个"URL 字符串"。这是 pydantic-settings 最常见的用法：**环境变量原子化，组合逻辑在代码里**。

`@lru_cache` 让 `get_settings()` 在整个进程内只构造一次 Settings 实例，全局共享。

---

## 四、数据层：`models/` + `migrations/`

### ORM 模型

- `base.py` — `DeclarativeBase` + `TimestampMixin`（统一 `created_at`/`updated_at`）
- `knowledge_base.py` — 知识库主表
- `document.py` — 文档 + chunk（**chunk 不单独建表，用 pgvector 和 Milvus 各自存**）
- `audit_log.py` — 审计日志

### 迁移

- `migrations/alembic.ini` — `script_location = .`（注意：从 `migrations/` 目录执行才 work）
- `migrations/env.py` — 导入所有 ORM 模型，让 Alembic 知道完整 schema

### 常见坑

在容器内跑迁移：

```bash
docker compose exec -w /app/migrations -e PYTHONPATH=/app:/app/src backend alembic upgrade head
```

三个参数缺一不可：

- `-w /app/migrations` — 让 alembic 找到 `alembic.ini`
- `PYTHONPATH=/app` — 支持 `from src.core.config import settings`
- `PYTHONPATH=/app/src` — 支持 `from models.knowledge_base import ...`

（这两种导入风格在 env.py 和 models/__init__.py 里并存，所以需要同时暴露两个路径）

---

## 五、文档摄入管线：`services/ingestion/`

从上传到可检索的四步：

```
上传文件 → parser.parse() → chunker.chunk() → embedder.embed_batch() → indexer.index()
   PDF          ParsedDocument    list[Chunk]      list[list[float]]     Milvus + PG
```

### 5.1 切分：`chunker.py`

核心算法（精简版）：

```python
def _split_text(self, text: str) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text)  # 按空白行分段
    chunks = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) <= self.chunk_size:
            current = (current + "\n\n" + para).strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)
    return chunks
```

**关键设计决策**：

- **以段落为单位贪心填充，保持语义边界**。不是严格按 `chunk_size` 硬切，所以会有"温和溢出"——这就是为什么 `design.md` 里 Property 11（`len(content) <= 2*S`）有 `2*` 的容差。
- **`content_type` 枚举封闭**：text / image / table 三种，对应 Property 14。

### 5.2 向量化：`embedder.py`

HTTP 调用 BGE-M3 服务（`models/serve.py`）。关键点：

- **批量 embed**（`embed_batch`）比单条调用快 10-50x，切分之后一次性全部 embed
- **兜底返回零向量而非抛异常**：这是个**双刃设计**——生产环境容错好，但测试/评测时可能把"上游挂了"伪装成"结果全为 0"。`eval/profiles/full.py` 的 `health_check` 里特意检测零向量来穿透这个兜底

### 5.3 索引：`indexer.py`

同一份 chunk 同时写两处：

- **PostgreSQL**：原文 + 元数据 + `tsvector` 全文索引（用于 BM25 稀疏检索）
- **Milvus**：chunk_id + 1024 维 float32 向量 + document_id（用于稠密相似度检索）

**为什么不只用 Milvus**：稠密向量擅长语义近似，但对**精确关键词匹配（专有名词、型号、缩写）**不如 BM25。混合才是 SOTA。

---

## 六、检索管线：`services/retrieval/`（本项目核心）

### 6.1 编排者：`retriever.py`

`Retriever.retrieve()` 是整条管线的"总调度"，四阶段：

```
阶段 1: query_rewriter.rewrite(query)         # 生成多个查询变体
阶段 2: 对每个变体分别跑 dense + (可选) sparse 检索
        → 融合：RRF 合并或去重
阶段 3: (可选) reranker.rerank(query, candidates, top_k)
阶段 4: similarity_threshold 过滤 + ChunkResult 格式化
```

**三个开关**：

- `use_hybrid=True` → 稀疏路也开，走 RRF 融合
- `use_rerank=True` → 候选集过一次 Cross-Encoder
- `query_rewriter` 始终开（内部有 fallback，失败会退化为只用原始 query）

**时间预算**：典型 full profile 一次 retrieve ~200-500ms（含两路检索 + rerank HTTP 往返）。

### 6.2 融合算法：`fusion.py` — 为什么是 RRF

RRF（Reciprocal Rank Fusion）的本质：

$$
\text{score}(d) = \sum_{q \in \text{queries}} \frac{1}{k + \text{rank}_q(d)}
$$

- $k=60$ 是 Cormack 原论文推荐的默认值
- 只关心**排名**，不关心各路分数的绝对尺度——这正是它比"加权分数和"更鲁棒的原因
- 当 $k$ 越大，各 rank 之间的差距越平滑（分数方差越小）——这就是 `design.md` Property 5 要验证的单调性

**代码里一个巧妙的细节**：

```python
if chunk_id not in scores:
    scores[chunk_id] = result.copy()
    scores[chunk_id]["score"] = 0.0
scores[chunk_id]["score"] += 1.0 / (k + rank)
```

用 `dict` 做去重的同时累加分数，于是"同一个 chunk 在 dense 和 sparse 里都出现 → 分数翻倍贡献"自动成立（对应 Property 6 共现提升）。

### 6.3 重排：`reranker.py`

Cross-Encoder 把 `(query, passage)` 拼在一起喂进同一个 Transformer 打分，比 Bi-Encoder（稠密向量点积）更精确但更贵。典型策略：

- 粗排：Bi-Encoder 取 top-50 或 top-100
- 精排：Cross-Encoder 重排回 top-5 或 top-10

**关键契约**（由 Property 8 表达）：**重排后的候选集 ⊆ 重排前的候选集**。即 reranker 只重打分、不引入新候选。

### 6.4 查询改写：`query_rewriter.py`

- 用 DeepSeek 把原始 query 生成 3-5 个不同角度的变体（同义改写、实体扩展、更具体/更抽象）
- **返回列表首位始终是原始 query**（保证 DeepSeek 挂了也有 fallback）
- 每个变体各跑一次 dense+sparse，结果通过 RRF 合并

---

## 七、生成层：`services/generation/deepseek_chat.py`

核心逻辑 40 行。

**Prompt 工程要点**：

```python
SYSTEM_PROMPT = """You are RAGForce, an enterprise knowledge base assistant.
Answer questions based solely on the provided context documents.
If the context does not contain enough information to answer, say so clearly.
Always cite the specific documents you used in your answer."""
```

三条约束：

1. "基于提供的文档回答"——防止幻觉
2. "上下文不足时明说"——防止编造
3. "引用具体文档"——可追溯性

**上下文组装**：

```python
context_text = "\n\n---\n\n".join(
    f"[Source {i+1}] {c['content']}"
    for i, c in enumerate(context_chunks)
)
```

带 `[Source N]` 的编号让模型知道怎么引用。

**流式**：`generate_stream` 返回 async generator，逐 chunk yield SSE `data: {...}` 行，`api/v1/chat.py` 的 `/stream` 端点包装成 FastAPI `StreamingResponse` 发给前端。

---

## 八、API 层：`api/v1/`

每个路由文件通常 <80 行。以 `chat.py` 为例：

```python
@router.post("", response_model=ChatResponse)
async def chat(request: ChatRequest):
    retrieval_result = await retriever.retrieve(...)
    context_chunks = [...]  # 格式化
    return await deepseek_chat.generate(query=..., context_chunks=...)
```

三步：**检索 → 整理上下文 → 生成**。没有任何 if/else，没有降级分支——全部沉到 service 层。

**`/chat/stream` 的一个细节**：

```python
headers={
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # 关键：禁止 nginx 缓冲 SSE
}
```

SSE 最常见的坑就是中间代理（nginx/cloudflare）把流缓冲成大块输出。`X-Accel-Buffering: no` 是告诉 nginx "别缓冲"。

---

## 九、中间件：`middleware/`

### 9.1 `audit.py`

拦截所有请求，在响应结束后把 `(user, action, resource, result)` 落到 `audit_logs` 表。**值得注意的设计选择**：审计失败不应阻塞主链路，所以这里用 try/except 把审计写入的异常吞掉并打 warning。

### 9.2 `metrics.py`

标准的 Prometheus 指标：

- `http_requests_total{method, path, status}` — 计数器
- `http_request_duration_seconds{method, path}` — 直方图

路由暴露在 `/metrics`，Prometheus（docker-compose 里的 `ragforce-prometheus`）定时来 scrape。

---

## 十、可观测性栈

| 服务 | 端口 | 职责 |
|---|---|---|
| Prometheus | 9090 | 拉取 `/metrics` 聚合 |
| Grafana | 3001 | 展示指标图表 |
| Jaeger | 16686 | 分布式追踪（OpenTelemetry） |
| Elasticsearch | 9200 | 存结构化日志 |
| Kibana | 5601 | 日志查询 UI |

日志通过 `core/logging.py` 配置成**双格式**（人类可读的 text + 结构化 JSON），JSON 行直接喂到 ELK。

---

## 十一、异步任务：`worker/`

Celery + RabbitMQ。当前主要一个任务：`doc_processing.process_document`。

**为什么用 Celery 而不是 FastAPI BackgroundTasks**：

- BackgroundTasks 跑在 API 进程里，OOM 会把 API 一起带崩
- Celery worker 是独立进程，崩了重启不影响 API
- 文档解析（PDF / Word OCR）可能几十秒甚至几分钟，必须异步化

上传 API 只做三件事：**保存文件 → 创建 Document 行（status=pending）→ 投递 Celery 任务**。用户拿到的是 `document_id`，轮询 `GET /documents/{id}` 等状态变为 `ready`。

---

## 十二、前端：`frontend/`（简要）

React 18 + Ant Design + Zustand + Vite，不展开细讲。几个关键文件：

- `src/pages/admin/` — 知识库管理、文档列表、审计、设置
- `src/pages/chat/` — 对话页（SSE 流式接收）
- `src/api/` — axios 封装的后端调用

SSE 接收的典型代码：

```typescript
const resp = await fetch('/api/v1/chat/stream', { method: 'POST', body: JSON.stringify(req) });
const reader = resp.body!.getReader();
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  // 解析 "data: {...}\n\n"，累加到 message 里
}
```

---

## 十三、数据流全景（一页图）

```
┌────────┐  POST /chat/stream    ┌──────────┐
│ Frontend│ ─────────────────────→│ FastAPI  │
└────────┘                        │ (/chat/*)│
                                  └────┬─────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
            ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
            │ retriever   │    │ deepseek    │    │ audit write │
            │  .retrieve()│    │  .generate()│    │   audit_logs│
            └──────┬──────┘    └──────┬──────┘    └─────────────┘
                   │                  │
     ┌─────────────┼─────────────┐    │
     ▼             ▼             ▼    │
┌─────────┐ ┌──────────┐ ┌──────────┐ │
│query_   │ │embedding │ │sparse    │ │
│rewriter │ │(BGE-M3)  │ │ (BM25    │ │
│ (DeepSk)│ │          │ │  on PG)  │ │
└─────────┘ └────┬─────┘ └────┬─────┘ │
                 │            │       │
                 ▼            │       │
            ┌─────────┐       │       │
            │dense    │       │       │
            │(Milvus) │       │       │
            └────┬────┘       │       │
                 │            │       │
                 └────────────┤       │
                              ▼       │
                         ┌──────┐     │
                         │ RRF  │     │
                         └───┬──┘     │
                             ▼        │
                      ┌────────────┐  │
                      │ reranker   │  │
                      │ (BGE-RE-v2)│  │
                      └─────┬──────┘  │
                            │         │
                            └────────→┤
                                      │
                                      ▼
                              ┌────────────┐
                              │ DeepSeek   │
                              │ chat API   │
                              │ (流式 SSE) │
                              └─────┬──────┘
                                    │
                                    ▼
                               回传给前端
```

## 十四、你应该掌握的关键概念

读完这份文档 + 源码，确保自己能不看书回答：

1. 为什么切分要保留段落边界而不是定长硬切？
2. 为什么 RRF 不需要知道各路分数的绝对尺度？
3. `use_hybrid=False` 时 `sparse_searcher.search` 还会被调用吗？为什么？
4. reranker 与 retriever 是什么关系——它能加候选吗？
5. 查询改写挂了会发生什么？管线会崩吗？
6. 一次完整的 chat 请求大概会产生多少次 HTTP/网络调用？

能答出来就说明你真的读进去了。接下来可以进 `03_testing_and_eval_deep_dive.md`。
