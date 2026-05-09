# RAGForce

企业级 RAG（检索增强生成）平台，基于 Advanced RAG 管线构建，支持多模态文档解析、混合检索、重排序与流式对话。

## 技术架构

```
用户请求 → FastAPI → 检索管线 → DeepSeek → 流式回复
              │
              ├── 文档摄入: PDF/Word → 解析 → 分块 → BGE-M3 向量化 → Milvus
              ├── 混合检索: 向量检索(Milvus) + BM25关键词(PostgreSQL) + RRF融合
              └── 可观测性: Prometheus + Jaeger + ELK + Grafana
```

## 技术栈

| 层 | 选型 |
|---|---|
| **后端框架** | FastAPI + Uvicorn（全链路异步） |
| **前端** | React 18 + TypeScript + Ant Design + Vite |
| **关系数据库** | PostgreSQL 16 + pgvector |
| **向量数据库** | Milvus 2.4 |
| **缓存** | Redis 7 |
| **消息队列** | RabbitMQ |
| **对象存储** | MinIO (S3 兼容) |
| **嵌入模型** | BGE-M3（1024 维，中英双语） |
| **重排序模型** | BGE-Reranker-v2-m3（Cross-Encoder） |
| **LLM** | DeepSeek Chat API |
| **可观测性** | OpenTelemetry + Jaeger + Prometheus + Grafana + ELK |
| **异步任务** | Celery |

## 快速开始

### 前置要求

- Docker 及 Docker Compose
- DeepSeek API Key（从 https://platform.deepseek.com 获取）
- BGE 模型文件（需下载到 `./models/` 目录）

### 1. 准备模型文件

```bash
# 下载 BGE-M3 嵌入模型
git lfs install
git clone https://huggingface.co/BAAI/bge-m3 ./models/bge-m3

# 下载 BGE-Reranker-v2-m3 重排序模型
git clone https://huggingface.co/BAAI/bge-reranker-v2-m3 ./models/bge-reranker-v2-m3
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 DEEPSEEK_API_KEY
```

### 3. 启动服务

```bash
docker compose up -d
```

启动后访问：
- **前端页面**: http://localhost:3000
- **API 文档**: http://localhost:8000/api/docs
- **Jaeger**: http://localhost:16686
- **Grafana**: http://localhost:3001
- **Kibana**: http://localhost:5601
- **RabbitMQ 管理**: http://localhost:15672

### 4. 初始化数据库

```bash
docker compose exec backend alembic upgrade head
```

## API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| GET | `/metrics` | Prometheus 指标 |
| GET | `/api/v1/dashboard/stats` | 仪表盘统计 |
| GET | `/api/v1/dashboard/recent-kbs` | 最近知识库 |
| GET | `/api/v1/knowledge-bases` | 知识库列表 |
| POST | `/api/v1/knowledge-bases` | 创建知识库 |
| GET | `/api/v1/knowledge-bases/{id}` | 知识库详情 |
| PATCH | `/api/v1/knowledge-bases/{id}` | 更新知识库 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库 |
| GET | `/api/v1/documents/kb/{kb_id}` | 文档列表 |
| POST | `/api/v1/documents/upload` | 上传文档 |
| GET | `/api/v1/documents/{id}` | 文档详情 |
| DELETE | `/api/v1/documents/{id}` | 删除文档 |
| POST | `/api/v1/retrieval` | 检索文档 |
| POST | `/api/v1/chat` | 对话（含引用） |
| POST | `/api/v1/chat/stream` | 流式对话（SSE） |
| GET | `/api/v1/audit-logs` | 审计日志 |

## 检索管线

```
用户Query
  │
  ▼
查询改写 (DeepSeek生成多角度表述)
  │
  ▼
多路召回 ──┬── 稠密检索 (BGE-M3 → Milvus)
           └── 稀疏检索 (BM25 → PostgreSQL full-text)
  │
  ▼
RRF 结果融合 (Reciprocal Rank Fusion)
  │
  ▼
重排序 (BGE-Reranker-v2-m3 Cross-Encoder)
  │
  ▼
上下文组装 + Token 截断
  │
  ▼
DeepSeek Chat 生成 (含引用溯源)
```

## 项目结构

```
ragforce/
├── backend/                  # FastAPI 后端
│   ├── src/
│   │   ├── api/v1/           # API 路由（dashboard/kb/documents/retrieval/chat/audit）
│   │   ├── core/             # 配置、数据库、异常、日志
│   │   ├── models/           # SQLAlchemy ORM 模型
│   │   ├── schemas/          # Pydantic 请求/响应模型
│   │   ├── services/
│   │   │   ├── ingestion/    # 文档解析/分块/向量化/索引
│   │   │   ├── retrieval/    # 检索管线（稠密/稀疏/融合/重排序/查询改写）
│   │   │   └── generation/   # DeepSeek 对话生成
│   │   ├── middleware/       # 审计、Prometheus 指标
│   │   └── worker/           # Celery 异步任务
│   └── migrations/           # Alembic 数据库迁移
├── frontend/                 # React 前端
│   └── src/pages/
│       ├── admin/            # 仪表盘、知识库管理、审计日志、系统设置
│       └── chat/             # 对话页面
├── models/                   # BGE 模型推理服务
├── infra/                    # Prometheus 配置
└── docker-compose.yml        # 13 个服务全栈编排
```

## 开发

### 后端

```bash
cd backend
pip install -e ".[dev]"
uvicorn src.main:app --reload
```

### 前端

```bash
cd frontend
npm install
npm run dev
```

### 数据库迁移

```bash
cd backend
alembic upgrade head        # 执行迁移
alembic revision --autogenerate -m "描述"  # 生成新迁移
```
