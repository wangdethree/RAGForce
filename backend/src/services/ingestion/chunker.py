import re

from schemas.ingestion import Chunk, ParsedDocument


class DocumentChunker:
    """将文档切分为带重叠的文本块"""

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    async def chunk(self, parsed_doc: ParsedDocument) -> list[Chunk]:
        chunks = []

        text_chunks = self._split_text(parsed_doc.text)
        for i, tc in enumerate(text_chunks):
            chunks.append(
                Chunk(
                    index=i,
                    content=tc,
                    content_type="text",
                    metadata={"source": "text"},
                )
            )

        for i, img in enumerate(parsed_doc.images):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=self._describe_image(img),
                    content_type="image",
                    metadata={
                        "page_num": img.page_num,
                        "image_index": img.index,
                        "ext": img.ext,
                    },
                )
            )

        for i, table in enumerate(parsed_doc.tables):
            chunks.append(
                Chunk(
                    index=len(chunks),
                    content=table.get("markdown", str(table)),
                    content_type="table",
                    metadata={"source": "table", "page_num": table.get("page_num", 0)},
                )
            )

        return chunks

    def _split_text(self, text: str) -> list[str]:
        paragraphs = re.split(r"\n\s*\n", text)
        chunks = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if len(current) + len(para) <= self.chunk_size:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(current)
                current = para

        if current:
            chunks.append(current)

        return chunks

    def _describe_image(self, img) -> str:
        return f"[Image] page={img.page_num}, index={img.index}, ext={img.ext}"


chunker = DocumentChunker()
