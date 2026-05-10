<!--
本 README 是 RAGForce 评测数据集（`backend/eval/`）的使用与构造指南。
通篇中文撰写，面向三类读者：

1. 想要了解 RAGForce 检索质量的读者 —— 读"数据集概览"与"报告产物说明"即可。
2. 想要在本地或 CI 上复跑评测的开发者 —— 读"CLI 使用示例"与"生成流程说明"。
3. 想要扩展数据集的贡献者 —— 读"JSONL 字段契约"与"扩展指南"。

注意事项：
- 文件中不包含任何 API key、内网 URL、真实 PII。
- 所有语料均为公开知识的二次整理，满足评测对"可复现、可离线运行"的要求。
- 更多设计背景请参见同目录 spec：`.kiro/specs/testing-and-eval-framework/design.md`。
-->

# RAGForce 评测数据集（`backend/eval/`）

> 本目录承载 RAGForce 离线检索质量评测所需的全部素材：中文语料、QA 集、评测配置、Profile 适配器、CLI 入口以及生成的报告。
> 数据集通过 `python -m eval.run` 驱动，支持零 Docker 的 `lite` profile 与真实 docker-compose 栈的 `full` profile。

---

## 1. 数据集概览

### 1.1 语料（`datasets/corpus/`）

共 **5 篇**中文 Markdown 文档，分别围绕 RAG 技术栈中的一个核心主题展开。全部采用 UTF-8 编码，单文件规模控制在 3 KB ~ 30 KB 区间内，便于在内存 Fakes 环境下快速入库。

| 文件名                 | 主题                                     | 字节数（约） |
|------------------------|------------------------------------------|-------------:|
| `doc_01_rag.md`        | 检索增强生成（RAG）技术概览              | 8.8 KB       |
| `doc_02_milvus.md`     | Milvus 向量数据库实战指南                | 8.6 KB       |
| `doc_03_bge.md`        | BGE-M3 嵌入模型与 BGE-Reranker-v2-m3     | 7.7 KB       |
| `doc_04_rrf.md`        | RRF 倒数排名融合方法详解                 | 8.1 KB       |
| `doc_05_deepseek.md`   | DeepSeek Chat 大模型与 RAG 生成链路      | 9.2 KB       |

每篇开头均有 HTML 注释形式的"写作意图"说明，便于后续贡献者理解语料的目标与边界。

### 1.2 QA 集（`datasets/qa_zh.jsonl`）

- **条目数**：25 条中文 QA（每行一个独立 JSON 对象，不含行内注释）。
- **难度分层**：

  | `difficulty` | 条数 | 设计意图                                                   |
  |--------------|------|-------------------------------------------------------------|
  | `easy`       | 12   | 直接问定义、字段、缩写等，词面重叠度高，sparse 主导即可命中。 |
  | `medium`     | 8    | 参数细节、同义表达、对比类问题，需要 dense 语义召回。        |
  | `hard`       | 5    | 跨文档综合，需要 `hybrid_rerank` 或 `full` 配置稳定命中。    |

- **语料覆盖**：每篇 corpus 均至少作为一条 QA 的 ground truth 出现，分布如下：

  | 文档              | 在 `relevant_doc_ids` 中出现次数 |
  |-------------------|-------------------------------:|
  | `doc_01_rag`      | 7                              |
  | `doc_02_milvus`   | 7                              |
  | `doc_03_bge`      | 7                              |
  | `doc_04_rrf`      | 5                              |
  | `doc_05_deepseek` | 5                              |

  `hard` 难度题目的 `relevant_doc_ids` 通常包含 2 ~ 3 个文档，因此累加值 31 大于 QA 条数 25。

---

## 2. JSONL 字段契约

`qa_zh.jsonl` 每行是一个独立 JSON 对象，字段契约如下：

| 字段                 | 类型                | 必填 | 语义                                                                   | 取值约束                                                                                             |
|----------------------|---------------------|:----:|------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------|
| `qid`                | `string`            | ✅   | 稳定唯一的题目编号。                                                   | 约定格式 `q\d{3}`（例：`q001`）。跨版本修订应保留旧 `qid` 以保持可追溯。                              |
| `query`              | `string`            | ✅   | 中文查询文本，面向最终用户的自然提问。                                 | 长度 ≥ 1；建议 5 ~ 40 个汉字；禁止包含密钥、真实 PII。                                               |
| `relevant_doc_ids`   | `string[]`          | ✅   | ground-truth 文档列表，元素为 `corpus/` 下文件的 basename 去扩展名。    | 长度 ≥ 1；每个元素必须在 `datasets/corpus/` 中存在对应文件（runner 启动时校验）。                    |
| `relevant_chunk_ids` | `string[]` \| `null`| ➖   | ground-truth chunk 列表；v1 由 ingest 阶段回填，手写数据集留 `null`。    | 若为 `null` 或缺省，评分会回退到基于 `document_id` 的成员判定。                                       |
| `answer`             | `string`            | ➖   | 参考答案文本；v1 不参与评分，仅用于人工审阅。                           | 不得包含密钥、内网地址、真实 PII；允许为空字符串或缺省。                                              |
| `difficulty`         | `string`            | ➖   | 难度分层，用于分层统计。                                                | 取值 ∈ `{"easy", "medium", "hard"}`；缺省时分层统计表会标记为 `unknown`。                            |

加载时若发现必填字段缺失、类型错误或 `relevant_doc_ids` 指向 corpus 中不存在的文件，CLI 将以 exit code `2` 退出，并在 stderr 打印违规 `qid` 与原因。

---

## 3. 生成流程说明

> 语料与 QA 集的设计思路来源于 `.kiro/specs/testing-and-eval-framework/design.md` 中的"数据集设计"章节。本节记录了我们在构造数据集时遵循的核心原则，便于后续贡献者按同样的节奏扩展。

### 3.1 语料撰写依据

- 主题取自 RAGForce 生产链路中实际使用到的技术栈：RAG 架构、Milvus 向量库、BGE 嵌入 / 重排模型、RRF 融合、DeepSeek Chat 生成模型。
- 内容全部为公开可查的二手资料整理，**不包含任何密钥、内网 URL、真实 PII**。
- 每篇字节数控制在 3 ~ 30 KB，既能产出足够多的 chunk 用于检索差异化，又不会让 `lite` profile 的内存 Fakes 运行过慢。
- 每篇开头用 HTML 注释给出"写作意图"，方便人工审阅时快速定位文档的关注点。

### 3.2 QA 题目设计原则

- **`easy`**：问题可以在单一文档的 1 ~ 2 句话内找到答案，且问句中的关键词基本能在原文被精确命中。该层用于检验 sparse 通道的基本召回能力。
- **`medium`**：问题围绕参数、细节、同义表达或轻度对比展开，原文措辞与查询措辞有一定距离，需要 dense 检索（BGE-M3）弥合语义鸿沟。
- **`hard`**：问题涉及跨 2 ~ 3 篇文档的综合，例如"Milvus 如何配合 BGE-M3 做 HNSW 索引"或"`hybrid_rerank` 与 `full` 比 `hybrid` 多启用哪些组件"。该层主要考察 RRF 融合与 cross-encoder 重排的增益。

### 3.3 可复现性要求

- JSONL 按 `qid` 升序写入；每次运行评测时 runner 会按相同顺序迭代，避免字典遍历顺序导致指标漂移。
- 手写数据集仅维护 `qid` / `query` / `relevant_doc_ids` / `answer` / `difficulty`；`relevant_chunk_ids` 允许为 `null`，由 ingest 阶段按需回填，便于一次数据集对应多个 chunker 配置。

---

## 4. CLI 使用示例

### 4.1 `lite` profile —— 零 Docker 默认模式

```bash
# 使用默认配置集（dense_only / hybrid / hybrid_rerank / full）与默认 k={5,10}
python -m eval.run \
  --profile lite \
  --dataset backend/eval/datasets/qa_zh.jsonl \
  --corpus backend/eval/datasets/corpus

# 仅对比 dense_only 与 hybrid，k 固定为 5
python -m eval.run \
  --profile lite \
  --configs dense_only,hybrid \
  --k 5 \
  --dataset backend/eval/datasets/qa_zh.jsonl \
  --corpus backend/eval/datasets/corpus
```

`lite` profile 通过 `backend/eval/profiles/lite.py` 把 `services.retrieval.retriever` 模块的五个单例替换为 `tests/fakes/*` 的内存 Fakes，**不依赖** Milvus、PostgreSQL、embedding / reranker HTTP 服务或 DeepSeek。

### 4.2 `full` profile —— 真实 docker-compose 栈

```bash
# 需要先在另一个终端启动依赖服务：docker compose up -d
python -m eval.run \
  --profile full \
  --configs full \
  --k 5,10 \
  --dataset backend/eval/datasets/qa_zh.jsonl \
  --corpus backend/eval/datasets/corpus
```

`full` profile 会在 ingest 与评测之间执行一次 warmup 查询，避免冷启动延迟污染 p50 / p95 指标。若关键依赖探活失败，runner 会以 exit code `3` 退出并在 stderr 列出未连通的依赖名。

### 4.3 常用参数速查

| 参数          | 默认值                                        | 说明                                                          |
|---------------|-----------------------------------------------|---------------------------------------------------------------|
| `--profile`   | `lite`                                        | `lite` 或 `full`。                                            |
| `--configs`   | 全部 4 个预设                                 | 逗号分隔的配置名，例如 `dense_only,hybrid_rerank`。           |
| `--k`         | `5,10`                                        | 逗号分隔的正整数列表，分别计算 Recall@k / MRR@k / nDCG@k。    |
| `--dataset`   | `backend/eval/datasets/qa_zh.jsonl`           | JSONL 路径。                                                  |
| `--corpus`    | `backend/eval/datasets/corpus`                | 语料目录路径。                                                |
| `--kb-id`     | `eval-kb`                                     | 入库时使用的 KB 标识。                                        |
| `--output-dir`| `backend/eval/reports/`                       | 报告输出目录。                                                |
| `--seed`      | `42`                                          | 随机种子，同时作用于 `random` / `numpy` / `hypothesis`。      |

退出码约定：`0`（成功）/ `2`（参数或数据校验失败）/ `3`（运行期依赖错误）。

---

## 5. 报告产物说明

### 5.1 输出位置

报告统一写入 `backend/eval/reports/`，文件名格式为：

```
YYYY-MM-DD-<profile>.md
```

例如：`2025-01-15-lite.md`、`2025-01-15-full.md`。该目录默认被 `.gitignore` 排除，只有手动挑选的基准报告才会随 PR 提交。

### 5.2 报告结构概览

生成的 Markdown 报告包含以下四个标准小节：

1. **元数据（Metadata）**：profile 名、数据集路径、条目数、参与配置集合、k 值列表、随机种子、wall time。所有数值型指标统一保留不超过 4 位小数。
2. **Summary 矩阵（每个 k 一张表）**：列为 `Config` / `Recall@k` / `MRR@k` / `nDCG@k` / `p50 ms` / `p95 ms`，行为参与比较的 `RetrievalConfig`。
3. **Per-query breakdown**：对前 10 条 query 列出每种配置下的命中情况（`✓` / `✗`），便于快速定位"哪类 query 在哪类配置下更容易失手"。
4. **How to reproduce**：打印完整可复制的 CLI 命令（含 `--profile` / `--configs` / `--k` / `--seed`）与环境准备步骤。

### 5.3 内容安全约束

- 报告**不包含** API key、secret、内网主机名或 IP。
- query 文本会被原样展示（数据集本身已脱敏），保证 GitHub 渲染器可直接预览。
- 报告使用相对路径与标准 Markdown 表格，避免引入外部图片依赖。

---

## 6. 扩展指南

### 6.1 新增一条 QA

1. 打开 `datasets/qa_zh.jsonl`，在末尾追加一个新的 JSON 对象（保持每行一个对象的格式）。
2. 取下一个未用过的 `qid`（例如当前最大为 `q025`，新增即 `q026`）。
3. 在 `relevant_doc_ids` 中填入 corpus 中已存在的文件 basename（去掉 `.md` 扩展名）。若 `ls backend/eval/datasets/corpus/` 里没有对应文件，请先按 6.2 新增语料。
4. 按题目设计原则（见 3.2）合理设置 `difficulty`。
5. 本地执行一次 `python -m eval.run --profile lite`：如果新增记录不合法，runner 会以 exit code `2` 退出并打印违规 `qid`。
6. 如需让 `relevant_chunk_ids` 生效，请保留为 `null`，由 ingest 阶段统一回填。

### 6.2 新增一篇 corpus

1. 文件名固定以 `doc_NN_` 前缀开头（`NN` 为两位递增编号），扩展名为 `.md`，编码为 UTF-8。
2. 单文件字节数控制在 3 KB ~ 30 KB 区间内，过短的文档难以产出足够多的 chunk 差异化。
3. 文件开头添加 HTML 注释，用一两句话概述"写作意图"，声明不含密钥 / PII。
4. 在 `datasets/qa_zh.jsonl` 中**至少**引用该文档一次（即至少有一条 QA 的 `relevant_doc_ids` 包含它的 basename），否则评测会跳过该语料。
5. 运行 `python -m eval.run --profile lite` 验证 ingest + 检索链路能正确加载新语料。

### 6.3 修订建议

- 任何对 `qid` 的修订都建议通过"新增替代 + 保留旧项"的方式进行，以免破坏历史报告的可追溯性。
- 如需调整整体分层比例（例如提升 `hard` 占比），请同步更新第 1.2 节的分布表与第 3.2 节的设计原则。
- 新增配置或指标需要先更新 `.kiro/specs/testing-and-eval-framework/design.md`，再在本 README 与 `backend/eval/config.py` 中落地。

---

## 7. 参考资料

- 设计文档：`.kiro/specs/testing-and-eval-framework/design.md`
- 需求文档：`.kiro/specs/testing-and-eval-framework/requirements.md`
- 任务清单：`.kiro/specs/testing-and-eval-framework/tasks.md`
- 指标定义：`backend/eval/metrics.py`（Recall@k、MRR@k、nDCG@k、percentile）
- 运行配置：`backend/eval/config.py`（`RetrievalConfig` 与 `PRESET_CONFIGS`）
