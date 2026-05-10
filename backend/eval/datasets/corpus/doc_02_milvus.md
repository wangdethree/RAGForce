<!-- 写作意图：为评测框架提供 Milvus 向量数据库的中文语料，覆盖定义、架构、索引类型、度量方式、典型参数、与其他向量库的对比以及常见使用场景，支撑后续 QA 集中的"Milvus 是什么 / HNSW 与 IVF 区别 / Milvus 如何扩展"等问题。全文仅包含公开信息，不涉及密钥或 PII。 -->

# Milvus 向量数据库实战指南

## 1. Milvus 是什么

Milvus 是一款面向大规模向量相似度搜索的开源向量数据库，最早由 Zilliz 开源，已进入 LF AI & Data 基金会的顶级项目孵化体系。它的核心能力是：接受高维稠密向量作为输入，以毫秒级延迟返回与查询向量最相似的若干条记录，并支持与标量字段（例如用户 ID、标签、时间戳）联合过滤。

在大语言模型与 RAG 系统兴起之前，向量检索就已经广泛应用于以图搜图、推荐系统、人脸识别、音频指纹等场景。而 RAG 的流行进一步让"向量数据库"成为基础设施的标配组件。Milvus 在国内外的工程实践中都有相当高的使用率，尤其是在需要**亿级甚至十亿级向量**的大规模场景下。

## 2. 总体架构

Milvus 采用存储与计算分离的云原生架构，核心组件包括：

- **Proxy**：接入层，负责请求路由、鉴权、限流。
- **Coordinator（Root / Query / Data / Index Coord）**：协调层，负责 DDL、查询调度、数据分片、索引构建的调度。
- **Worker 节点（Query Node / Data Node / Index Node）**：执行层，分别负责查询、写入、索引构建。
- **对象存储（MinIO / S3 / OSS）**：持久化层，存放向量数据段与索引文件。
- **元数据存储（etcd）**：保存集合、分区、字段定义等元信息。
- **消息队列（Pulsar / Kafka）**：承载实时写入的 WAL，保证可靠性。

这种架构的好处是：节点可以按负载单独扩缩容，存储成本与计算成本解耦；坏处是部署复杂度较高，初学者往往会用 Milvus Lite 或 Docker Compose 的 Standalone 模式入门。

## 3. 集合、分区与字段

Milvus 的数据组织层次是：

- **Collection**：相当于关系数据库中的表，一个 Collection 必须包含一个向量字段和一个主键字段。
- **Partition**：对 Collection 的横向切分，可按业务维度（例如按租户、按时间）划分。
- **Field**：字段支持 INT64、VARCHAR、FLOAT、BOOL、JSON、ARRAY 以及 FLOAT_VECTOR、BINARY_VECTOR、SPARSE_FLOAT_VECTOR 等向量类型。

自 Milvus 2.4 起，单个 Collection 也可以同时包含多个向量字段，从而在一张表里存放"稠密向量 + 稀疏向量 + 重排特征"等多路索引，非常契合混合检索的需求。

## 4. 度量方式

Milvus 支持的距离/相似度度量有：

- **L2**（欧氏距离）：分数越小越相似。
- **IP**（内积）：用于未归一化的向量。
- **COSINE**（余弦相似度）：在内部等价于对归一化后向量做内积；BGE、M3E 这类中文嵌入模型默认就是归一化输出，搭配 COSINE 或 IP 都可。
- **HAMMING / JACCARD**：用于二值向量。

选度量方式的原则：嵌入模型作者推荐什么度量就用什么度量；如果模型输出已经归一化，COSINE 与 IP 在排序上完全等价，IP 计算量更小。

## 5. 索引类型

Milvus 支持多种向量索引，选择合适的索引可以在召回率、查询延迟、内存占用之间取得平衡：

- **FLAT**：暴力枚举，零召回损失，适合小规模（十万级以下）数据集或"ground truth"参考。
- **IVF_FLAT / IVF_SQ8 / IVF_PQ**：基于倒排文件（Inverted File）与聚类的索引，训练阶段把向量聚为 `nlist` 个簇，查询阶段只扫描最接近的 `nprobe` 个簇。IVF_SQ8 与 IVF_PQ 引入量化，进一步压缩内存。
- **HNSW**：Hierarchical Navigable Small World 图索引，查询延迟极低、召回率高，是中小规模 RAG 场景最常见的选择。
- **DISKANN**：面向磁盘优化的大规模索引，牺牲一点延迟以支撑十亿级数据。
- **SCANN**：在特定硬件上性能优秀，适合单机超大规模。
- **SPARSE_INVERTED_INDEX / SPARSE_WAND**：用于稀疏向量（例如 SPLADE、BGE-M3 的 lexical 输出）的索引。

## 6. HNSW 与 IVF 的参数

HNSW 是 RAG 场景默认选择，常见参数：

- `M`：每个节点的最大邻居数，典型值 `8`–`48`。越大召回越稳，但内存越多。
- `efConstruction`：建索引时的搜索宽度，典型值 `64`–`512`。越大索引质量越高。
- `ef`（查询时）：搜索宽度，典型值 `top_k * 2` 到几百。越大召回越高但延迟越长。

IVF 系列常见参数：

- `nlist`：簇数量，经验公式为 `4 * sqrt(N)` 或 `16 * sqrt(N)`，N 为向量数。
- `nprobe`：查询时扫描的簇数量，典型值 `8`–`64`。

实际调参时，应结合线上 QPS、召回率要求、内存预算做 A/B 测试，不能盲目照搬默认值。

## 7. 混合检索支持

在 Milvus 2.4+ 中，单集合可以定义多个向量字段并分别建立索引，例如一个稠密字段 `dense` + 一个稀疏字段 `sparse`。查询时可以用 `AnnSearchRequest` 分别发起两路检索，再用 `RRFRanker` 或 `WeightedRanker` 把两路结果融合。这个设计对"稠密 + 稀疏"混合检索非常友好，本项目 RAGForce 正是基于这一能力实现混合检索链路。

## 8. 标量过滤与分区

Milvus 支持在向量检索的同时做标量字段过滤，例如：

```
expr = 'tenant_id == "T001" and created_at > 1700000000'
```

过滤通常发生在向量检索之前（pre-filter）或之后（post-filter），Milvus 会根据选择率自适应决定。对高基数、强选择率字段，建议显式建立标量索引（BITMAP / SORT）提升过滤效率。

## 9. 部署形态

Milvus 提供多种部署形态：

- **Milvus Lite**：以 Python 进程内库的形式运行，适合快速实验和单机小数据集。
- **Standalone**：以单容器方式运行，包含 etcd、MinIO、Milvus 本体，适合开发联调和中小规模生产。
- **Cluster**：完整的云原生集群，按组件独立扩展，适合生产环境。
- **Zilliz Cloud**：官方托管服务，免运维。

本项目 RAGForce 在 Docker Compose 下启动 Standalone 模式，配合 etcd 和 MinIO 即可完成完整链路联调；评测框架里我们则通过 Fake 实现把 Milvus 替换为内存版本，以便零容器环境下也能跑完整个流水线。

## 10. 与其他向量库的对比

- **Milvus vs Qdrant**：Qdrant 以单体化 Rust 实现著称，部署简洁、过滤表达力强；Milvus 胜在扩展性与生态。
- **Milvus vs Weaviate**：Weaviate 自带对象 schema 和多模态能力；Milvus 更纯粹地围绕向量检索做深做透。
- **Milvus vs pgvector**：pgvector 把向量检索能力嵌入 PostgreSQL，适合小规模、与现有关系库深度融合的场景；当数据量超过千万级或需要更激进的索引压缩时，Milvus 的专业化优势更明显。
- **Milvus vs Elasticsearch / OpenSearch**：ES 在关键词检索上最成熟，近年来也引入了 kNN 支持，但在亿级向量规模下，Milvus 的性能与成本优势依旧显著。

## 11. 常见问题与最佳实践

1. **写入后立即搜索不可见**：Milvus 写入默认异步落盘，需要等待 `flush` 或使用 `Consistency Level = Strong`。
2. **内存 OOM**：HNSW 索引完整加载到内存，集合过大时要评估内存预算，必要时改用 DISKANN。
3. **主键冲突**：Milvus 2.x 默认不自动检测主键重复，业务侧要自己保证唯一性或使用 UPSERT。
4. **索引选择**：数据量 10 万以内用 FLAT，百万级用 HNSW，十亿级考虑 DISKANN。
5. **Partition 过多**：单 Collection 下 Partition 数量不宜超过几千，过多会拖慢元数据管理。
6. **与 embedding 模型解耦**：索引配置应跟随嵌入维度（例如 BGE-M3 为 1024），变更模型时必须重建集合。

## 12. 小结

Milvus 在大规模向量检索领域是目前最成熟的开源选择之一，它的云原生架构、丰富的索引类型、对混合检索的原生支持，使其非常适合承担企业级 RAG 系统的底座。正确使用 Milvus 的关键不是"会调用 API"，而是**理解每个索引参数背后的权衡**，并结合自己的数据规模与业务需求做持续调优。
