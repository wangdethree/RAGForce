"""评测语料入库模块 —— 将 ``datasets/corpus/`` 下的 Markdown 文档装入
dense/sparse 存储，供后续检索评测直接消费。

本模块是 eval 框架的"数据准备"环节，串联以下 **五步稳定流水线**
（与下方 ``ingest_corpus`` 函数体内的行内注释一一对应）：

1. **读取**：按文件名升序遍历 ``corpus_dir`` 下全部 ``*.md``，以 UTF-8 读入
   正文。文件名排序保证每次运行看到的语料顺序都完全一致，这是评测可复现性
   （Requirement 18.4）的基石之一。
2. **解析**：把 Markdown 原文包装成生产 ingestion 管线使用的
   ``ParsedDocument``（只填 ``text`` 字段，``pages / images / tables`` 置空）。
   复用生产 schema 是为了让 chunker 的行为与真实入库链路一致。
3. **切分**：调用 ``services.ingestion.chunker.DocumentChunker.chunk`` 切分
   每篇文档，得到 ``list[Chunk]``。未覆写 ``chunker`` 参数时默认新建一个
   ``DocumentChunker()``，与生产默认参数（``chunk_size=512`` /
   ``chunk_overlap=50``）保持一致。
4. **向量化**：对切出来的所有 chunk 的 ``content`` **一次性批量 embed**
   （单篇文档一次 ``embedder.embed_batch`` 调用），降低网络/计算开销；Fake
   embedder 也因此得到确定性的向量。
5. **索引**：将所有 record 汇总后 **一次性 seed** 到 dense/sparse 存储，避免
   多次 seed 导致的边界条件；同时返回 ``{doc_stem: [chunk_id, ...]}`` 映射，
   供 runner 把 QA 集的 ``relevant_doc_ids`` 展开为 ``relevant_chunk_ids``
   （Requirement 11.6）。

对应任务：``tasks.md`` §13.3。对应需求：Requirements 11.6、18.4。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

# 复用生产切分器与 ParsedDocument schema —— 本模块 **不** 重写切分逻辑，
# 保证 eval 与真实 ingestion 看到相同的 chunk 结构（Requirement 19.4）。
from schemas.ingestion import ParsedDocument
from services.ingestion.chunker import DocumentChunker


# ---------------------------------------------------------------------------
# duck-typed 端口签名（仅用于类型提示，运行时仍然走 duck typing）
# ---------------------------------------------------------------------------
class _EmbedderLike(Protocol):
    """``ingest_corpus`` 所需的 embedder 最小契约。"""

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:  # pragma: no cover - protocol
        ...


class _SeedableStore(Protocol):
    """``ingest_corpus`` 所需的 dense/sparse 存储最小契约。"""

    def seed(self, kb_id: str, records: list[dict[str, Any]]) -> None:  # pragma: no cover - protocol
        ...


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
async def ingest_corpus(
    corpus_dir: Path,
    kb_id: str,
    *,
    embedder: _EmbedderLike,
    dense_store: _SeedableStore,
    sparse_store: _SeedableStore,
    chunker: DocumentChunker | None = None,
) -> dict[str, list[str]]:
    """把 ``corpus_dir`` 下的 Markdown 语料灌入 dense + sparse 存储。

    参数
    ----
    corpus_dir:
        评测语料目录（一般是 ``backend/eval/datasets/corpus``）。函数内部使用
        ``pathlib.Path`` 统一处理，兼容 Windows / Linux 路径分隔符
        （Requirement 20.5）。
    kb_id:
        目标知识库标识。评测默认使用 ``"eval-kb"``，由 runner 传入。
    embedder:
        需暴露 ``async embed_batch(list[str]) -> list[list[float]]`` 的对象；
        lite profile 下为 ``FakeEmbeddingService``，full profile 下为生产
        embedding service。
    dense_store / sparse_store:
        需暴露 ``seed(kb_id, list[dict])`` 的存储对象；lite profile 下分别为
        ``InMemoryDenseSearcher`` 与 ``InMemorySparseSearcher``。
    chunker:
        可选的切分器实例；缺省时自动创建 ``DocumentChunker()``。允许测试注入
        自定义 chunk_size 的实例，但 **禁止** 在此重写切分算法——生产链路的
        切分规则应作为唯一事实来源。

    返回
    ----
    ``dict[str, list[str]]``：键是文档的 ``Path.stem``（例如 ``"doc_01_rag"``），
    值是该文档生成的 ``chunk_id`` 列表，按 chunk index 升序排列。runner 可据
    此把 ``relevant_doc_ids`` 展开为 ``relevant_chunk_ids``；当 QA 记录没有
    显式 ``relevant_chunk_ids`` 时，评分阶段回退到基于 ``document_id`` 的
    成员判定（Requirement 11.6）。

    稳定性保证
    ----------
    - 文件按 ``sorted()`` 的默认字典序迭代，保证相同语料目录下每次运行的处理
      顺序完全一致（Requirement 18.4）。
    - ``chunk_id`` 使用 ``f"{doc_stem}#{chunk_index:04d}"`` 格式，内嵌 chunk
      在文档内的序号（4 位零填充足够覆盖每篇文档数万个 chunk），既人类可读又
      跨运行稳定。
    """

    # ---------- 0. 参数兜底 ----------
    # 若调用方未传 chunker，则复用生产默认参数（chunk_size=512, chunk_overlap=50）
    # 与真实 ingestion 管线保持一致。
    if chunker is None:
        chunker = DocumentChunker()

    # 汇总缓冲区：所有文档的所有 record 最终一次性 seed 到两个存储，避免重复
    # seed 带来的语义模糊（例如"多次 seed 是覆盖还是追加？"）。
    all_records: list[dict[str, Any]] = []
    # 返回映射：doc_stem -> chunk_id 列表（按 chunk.index 升序）。
    doc_to_chunk_ids: dict[str, list[str]] = {}

    # ---------- 1. 读取：按文件名升序遍历 *.md ----------
    # glob("*.md") 的返回顺序在不同文件系统上不保证，显式 sorted 以满足
    # Requirement 18.4（稳定迭代顺序）。
    md_files = sorted(Path(corpus_dir).glob("*.md"))

    for md_path in md_files:
        # ---------- 1a. 读取 UTF-8 文本 ----------
        # 使用 pathlib.Path.read_text 显式指定 encoding="utf-8"，避免 Windows
        # 默认 GBK 造成中文乱码（Requirement 20.4）。
        text = md_path.read_text(encoding="utf-8")
        # 以文件名去扩展名作为 document_id，例如 "doc_01_rag"。
        doc_stem = md_path.stem

        # ---------- 2. 解析：包装为 ParsedDocument ----------
        # Markdown 语料不含图片/表格二进制，因此只填 text，其余置空列表。
        # 复用生产 schema 保证 chunker 的行为与真实链路一致。
        parsed = ParsedDocument(text=text, pages=[], images=[], tables=[])

        # ---------- 3. 切分：调用生产 DocumentChunker ----------
        # chunker.chunk 是 async 函数，返回 list[Chunk]；Chunk 已经按 index
        # 连续递增（Requirement 8.3），这里只需 enumerate 加上文档前缀。
        chunks = await chunker.chunk(parsed)

        # 某些退化输入（空语料）可能返回空列表；跳过以避免无意义的 embedder 调用。
        if not chunks:
            doc_to_chunk_ids[doc_stem] = []
            continue

        # ---------- 4. 向量化：单篇文档一次批量 embed ----------
        # 只 embed 文本 content，顺序与 chunks 一一对应。
        contents = [ch.content for ch in chunks]
        embeddings = await embedder.embed_batch(contents)

        # ---------- 5. 索引 & 映射输出 ----------
        # 构造 record 字典（与生产 dense/sparse searcher 返回字段对齐：
        # chunk_id / document_id / content / content_type / embedding）。
        chunk_ids: list[str] = []
        for ch, emb in zip(chunks, embeddings):
            # 稳定 chunk_id 方案：doc_stem + '#' + 4 位零填充的 chunk 索引
            chunk_id = f"{doc_stem}#{ch.index:04d}"
            record: dict[str, Any] = {
                "chunk_id": chunk_id,
                "document_id": doc_stem,
                "content": ch.content,
                "content_type": ch.content_type,
                "embedding": emb,
            }
            all_records.append(record)
            chunk_ids.append(chunk_id)

        # 把当前文档的 chunk_id 列表写入返回映射；列表已按 chunk.index 升序
        # （chunker 保证 index 0..N-1 连续），供下游稳定引用。
        doc_to_chunk_ids[doc_stem] = chunk_ids

    # 汇总完毕 —— 分别向 dense / sparse 存储一次性 seed 全部 record，
    # 顺序与 all_records 一致。两路存储共享同一份 record 副本的字段集合
    # （dense 使用 embedding，sparse 使用 content），因此可以共用同一批
    # 字典对象。
    dense_store.seed(kb_id, all_records)
    sparse_store.seed(kb_id, all_records)

    return doc_to_chunk_ids
