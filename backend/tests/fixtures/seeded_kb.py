"""预置知识库样例记录工厂。

本模块提供一组**纯函数工厂**（不依赖 pytest fixture 基础设施），用于给
集成测试、属性测试与 API 契约测试提供**稳定、可复现**的样例数据。

模块设计遵循 ``design.md`` LLD-5 的 ``_sample_records`` 语义，并按
``tasks.md`` 3.2 子任务的要求拆分成三类工厂：

1. :func:`build_chunk_records` —— 返回 5 条具备语义差异的中文 chunk 记录
   （跨 3 个 document），每条含 ``chunk_id / document_id / content /
   content_type``。**不包含** ``embedding`` 字段：方便稀疏检索器、
   ORM 转换层等不需要向量的使用方直接消费。

2. :func:`build_seed_records` —— 协程工厂，基于
   :func:`build_chunk_records` 再为每条记录追加通过
   ``FakeEmbeddingService`` 计算出的 ``embedding`` 字段。典型用法是
   集成测试的 ``seeded_kb`` fixture 在一次 await 内批量生成后喂给
   ``InMemoryDenseSearcher.seed`` / ``InMemorySparseSearcher.seed``。

3. :func:`build_orm_rows` —— 返回 :class:`KnowledgeBase` /
   :class:`Document` / :class:`DocumentChunk` 的 ORM 实例列表
   （打包在 :class:`ORMRows` NamedTuple 中），供 API 契约测试通过
   ``session.add_all(...)`` 直接写入内存 SQLite。

> **语义差异性**：5 条 chunk 分别覆盖 5 个截然不同的主题
> （Milvus 向量库、IVF 索引、BGE-M3 句向量、Cross-Encoder 重排、RRF 融合），
> 保证下游检索管线的打分能够区分命中与非命中，避免测试因样本过于相似
> 而出现"怎么打分排序都一样"的退化。

对应需求：Requirements 3.1、3.5、3.6、7.1、7.2、7.5。
"""

from __future__ import annotations

from typing import Any, NamedTuple, Protocol

# 直接从生产模型 import；pytest 的 ``pythonpath = ["src"]`` 配置保证
# ``models.knowledge_base`` / ``models.document`` 可被解析
# （详见 ``pyproject.toml`` 的 ``[tool.pytest.ini_options]``）。
from models.document import Document, DocumentChunk, DocumentStatus
from models.knowledge_base import KnowledgeBase


# --------------------------------------------------------------------------- #
# 供本模块使用的 duck-typed 协议：真实 ``FakeEmbeddingService`` 满足此契约
# --------------------------------------------------------------------------- #
class _EmbeddingLike(Protocol):
    """仅声明 :func:`build_seed_records` 所需的最小接口（duck typing）。

    Python 运行时不做结构子类型检查，此协议只是**文档化**形状；任何暴露
    ``async embed_single(text) -> list[float]`` 的对象都可传入。
    """

    async def embed_single(self, text: str) -> list[float]:
        ...  # pragma: no cover  —— 协议占位


# --------------------------------------------------------------------------- #
# 1. Chunk 记录工厂
# --------------------------------------------------------------------------- #
def build_chunk_records() -> list[dict[str, Any]]:
    """返回 5 条跨 3 篇文档的中文 chunk 样例。

    分布说明：

    - ``d1`` 文档下 2 条：围绕 *Milvus 向量数据库* 与 *IVF_FLAT 索引*，
      两条共享关键词 "Milvus" 以验证同一文档多 chunk 的检索场景。
    - ``d2`` 文档下 2 条：围绕 *BGE-M3 句向量模型* 与 *Cross-Encoder
      重排器*，两条主题完全不同以产生跨文档的语义差异。
    - ``d3`` 文档下 1 条：围绕 *RRF 倒数排名融合*，便于测试"最终排序
      中出现跨多个文档的候选"的融合行为。

    返回值字段（每条 dict）：

    ``chunk_id``      : 稳定主键 ``"c1"..."c5"``；
    ``document_id``   : 所属文档 id ``"d1" / "d2" / "d3"``；
    ``content``       : 中文原文，与设计文档 LLD-5 保持一致；
    ``content_type``  : 统一为 ``"text"``（纯文本，不走 image/table 分支）。

    本函数**不写入任何存储**，仅返回新构造的字典列表。调用方可以自由
    修改返回结果而不影响下一次调用的确定性（每次都新建字典）。
    """

    # 注意：这里显式构造 list[dict]，**不**在模块级做常量缓存 —— 若缓存
    # 会导致不同测试之间共享可变状态，违反测试隔离原则。
    return [
        {
            # chunk c1 @ d1：覆盖 "Milvus 向量数据库" 这一概念类查询
            "chunk_id": "c1",
            "document_id": "d1",
            "content": "Milvus 是一个开源的向量数据库，支持高性能相似度搜索。",
            "content_type": "text",
        },
        {
            # chunk c2 @ d1：覆盖 "IVF_FLAT 索引加速" 这一细节类查询
            "chunk_id": "c2",
            "document_id": "d1",
            "content": "Milvus 使用 IVF_FLAT 等索引结构加速向量检索。",
            "content_type": "text",
        },
        {
            # chunk c3 @ d2：覆盖 "BGE-M3 句向量模型" 这一模型类查询
            "chunk_id": "c3",
            "document_id": "d2",
            "content": "BGE-M3 是一个支持中英双语的句向量模型，输出 1024 维向量。",
            "content_type": "text",
        },
        {
            # chunk c4 @ d2：覆盖 "Cross-Encoder 重排序" 这一精排类查询
            "chunk_id": "c4",
            "document_id": "d2",
            "content": "Cross-Encoder 重排序模型对候选文档精排。",
            "content_type": "text",
        },
        {
            # chunk c5 @ d3：覆盖 "RRF 倒数排名融合" 这一融合算法类查询
            "chunk_id": "c5",
            "document_id": "d3",
            "content": "RRF 倒数排名融合将多路检索结果合并。",
            "content_type": "text",
        },
    ]


async def build_seed_records(
    kb_id: str,
    embedding_service: _EmbeddingLike,
) -> list[dict[str, Any]]:
    """基于 :func:`build_chunk_records` 为每条记录追加 ``embedding`` 字段。

    参数
    ----
    kb_id:
        目标知识库标识。当前**仅用于文档化意图**（返回记录不含 kb 字段，
        存储方会在 ``seed(kb_id, records)`` 时自行带入），保留该参数是
        为了与调用方 ``seeded_kb`` fixture 的签名对齐并便于未来扩展。
    embedding_service:
        任何满足 :class:`_EmbeddingLike` 协议的对象；测试场景下通常是
        :class:`tests.fakes.embedding.FakeEmbeddingService` 实例。

    返回
    ----
    list[dict[str, Any]]
        每条记录在 :func:`build_chunk_records` 基础上追加
        ``"embedding": list[float]`` 字段，向量由 ``embedding_service
        .embed_single(content)`` 确定性计算。

    使用约定
    --------
    - 本函数是 **async**：``embed_single`` 是协程接口，必须用 ``await``
      调用；调用方（如 ``seeded_kb`` fixture）同样需要声明为 async。
    - 按 chunk 列表的原始顺序顺次调用 ``embed_single``，保证确定性
      （见 Requirement 18.3 / 18.4：Fakes 对相同输入返回相同输出，
      并以稳定顺序迭代以避免报告漂移）。
    - 返回**新字典**，不修改 :func:`build_chunk_records` 的原始结果。
    """

    # kb_id 参数不直接写入记录字典（存储方按 kb_id 分桶），仅在文档中说明用意
    _ = kb_id  # 显式标注"有意保留此参数"以消除静态检查器的未使用提示

    # 先拿到基础记录，再逐条计算向量
    base_records = build_chunk_records()

    seeded: list[dict[str, Any]] = []
    for record in base_records:
        # 对 content 逐条计算 embedding；顺序与 base_records 保持一致
        # 以满足 Requirement 18.4（按稳定顺序迭代）
        embedding = await embedding_service.embed_single(record["content"])
        # 浅拷贝原 record 并追加 embedding 字段，避免污染 base_records
        seeded.append({**record, "embedding": embedding})

    return seeded


# --------------------------------------------------------------------------- #
# 2. ORM 行工厂（供 API 契约测试插入内存 SQLite）
# --------------------------------------------------------------------------- #
class ORMRows(NamedTuple):
    """聚合 KB / Document / Chunk 三类 ORM 实例的返回容器。

    使用 :class:`NamedTuple` 而非 ``dict``，好处：

    - 对调用方 ``session.add_all(rows.knowledge_bases + rows.documents +
      rows.chunks)`` 提供类型友好的字段访问；
    - 不可变：避免测试内部误修改后影响其它用例。
    """

    #: 知识库 ORM 实例列表，长度 = ``num_kbs``
    knowledge_bases: list[KnowledgeBase]
    #: 文档 ORM 实例列表，长度 = ``num_kbs * num_docs``
    documents: list[Document]
    #: 文档 chunk ORM 实例列表，长度 = ``num_kbs * num_docs * _CHUNKS_PER_DOC``
    chunks: list[DocumentChunk]


# 每篇文档下固定生成 2 条 chunk，既能覆盖"多 chunk 聚合"场景，又保持
# ORM 行数在 API 契约测试里足够小，插入/断言都很廉价。
_CHUNKS_PER_DOC = 2


def build_orm_rows(num_kbs: int = 1, num_docs: int = 2) -> ORMRows:
    """构造 KB / Document / DocumentChunk 的 ORM 实例集合。

    参数
    ----
    num_kbs:
        生成的 :class:`KnowledgeBase` 数量，默认 1。
    num_docs:
        **每个** KB 下生成的 :class:`Document` 数量，默认 2。
        所以文档总数 = ``num_kbs * num_docs``。

    返回
    ----
    ORMRows
        - ``knowledge_bases``：长度 = ``num_kbs``；
        - ``documents``：长度 = ``num_kbs * num_docs``，``kb_id`` 字段
          正确指向其所属 KB；
        - ``chunks``：长度 = ``num_kbs * num_docs * _CHUNKS_PER_DOC``，
          ``document_id`` 字段正确指向其所属 Document，
          ``chunk_index`` 从 0 起逐文档递增。

    id 稳定性
    --------
    为了让 API 契约测试可以以字面量断言响应体中的 id，本工厂**不使用**
    ORM 默认的 uuid4 生成器，而是显式赋予稳定 id：

    - KnowledgeBase id: ``"kb-fixture-{i:03d}"``（i 从 1 起）
    - Document id:       ``"doc-{kb_i:03d}-{doc_j:03d}"``
    - DocumentChunk id:  ``"chunk-{kb_i:03d}-{doc_j:03d}-{chunk_k:02d}"``

    其它字段使用生产 schema 的合理默认值：

    - KnowledgeBase.name: ``"fixture-kb-{i}"``；description 取空串
    - Document.filename / file_type / storage_path：生成稳定占位值；
      ``status`` 置为 :data:`DocumentStatus.READY` 以模拟"可被检索"的
      终态；``chunk_count`` 填充为实际 chunk 数。
    - DocumentChunk.content：复用 :func:`build_chunk_records` 的首条
      content 模板循环填充，确保每条 chunk 仍具有**中文语义**，避免
      sparse 打分时出现空命中。

    参数校验
    --------
    当 ``num_kbs`` 或 ``num_docs`` 非正数时抛 :class:`ValueError`，
    防止静默返回空集合导致后续断言难以调试。
    """

    if num_kbs <= 0:
        raise ValueError(f"num_kbs 必须为正整数，收到 {num_kbs}")
    if num_docs <= 0:
        raise ValueError(f"num_docs 必须为正整数，收到 {num_docs}")

    # 提前取一次 chunk 内容模板，作为每条 chunk 的 content 池循环使用
    # 这样即使 num_kbs/num_docs 组合产生大量 chunk，也能保证所有 content
    # 都是具有语义的中文文本（而非无意义的 "chunk-xxx" 占位串）
    content_pool = [r["content"] for r in build_chunk_records()]

    kbs: list[KnowledgeBase] = []
    docs: list[Document] = []
    chunks: list[DocumentChunk] = []

    for kb_i in range(1, num_kbs + 1):
        # ---- 知识库 ----
        kb_id = f"kb-fixture-{kb_i:03d}"
        kb = KnowledgeBase(
            id=kb_id,
            name=f"fixture-kb-{kb_i}",
            description="",  # 保持简洁；API 契约测试只关心 name/id
            top_k=5,
            similarity_threshold=0.7,
            # document_count 会由上层业务在 add_documents 时维护，这里按
            # fixture 的 ground truth 直接写 num_docs
            document_count=num_docs,
        )
        kbs.append(kb)

        for doc_j in range(1, num_docs + 1):
            # ---- 文档 ----
            doc_id = f"doc-{kb_i:03d}-{doc_j:03d}"
            doc = Document(
                id=doc_id,
                kb_id=kb_id,
                filename=f"fixture-doc-{kb_i}-{doc_j}.md",
                file_type="md",
                file_size=1024,  # 稳定占位值；API 契约测试不关心具体字节数
                storage_path=f"/fixtures/{kb_id}/{doc_id}.md",
                status=DocumentStatus.READY,  # 终态，表示"已完成索引可被检索"
                error_message="",
                chunk_count=_CHUNKS_PER_DOC,
            )
            docs.append(doc)

            for chunk_k in range(_CHUNKS_PER_DOC):
                # ---- chunk ----
                chunk_id = f"chunk-{kb_i:03d}-{doc_j:03d}-{chunk_k:02d}"
                # 从 content_pool 循环取内容，保证中文语义
                content = content_pool[(doc_j + chunk_k) % len(content_pool)]
                chunks.append(
                    DocumentChunk(
                        id=chunk_id,
                        document_id=doc_id,
                        chunk_index=chunk_k,  # 从 0 起单调递增（Requirement 8.3 的口径）
                        content=content,
                        content_type="text",
                        metadata_json="{}",
                        # vector_id 指向 Milvus 的主键；测试层不接 Milvus，
                        # 此处填稳定占位值即可，便于字符串断言
                        vector_id=f"vec-{chunk_id}",
                        embedding_score=0.0,
                    )
                )

    return ORMRows(knowledge_bases=kbs, documents=docs, chunks=chunks)


__all__ = [
    "ORMRows",
    "build_chunk_records",
    "build_orm_rows",
    "build_seed_records",
]
