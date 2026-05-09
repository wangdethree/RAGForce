"""Celery 异步文档处理管线任务"""

from celery import Celery

from src.core.config import settings
from src.services.ingestion.parser import document_parser
from src.services.ingestion.chunker import chunker
from src.services.ingestion.embedder import embedding_service
from src.services.ingestion.indexer import milvus_indexer

celery_app = Celery(
    "ragforce",
    broker=settings.RABBITMQ_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(bind=True, max_retries=3)
def process_document(self, document_id: str, kb_id: str, file_path: str, file_type: str):
    """完整文档处理管线：解析 → 切块 → 向量化 → 索引"""
    import asyncio

    async def _process():
        parsed = await document_parser.parse(file_path, file_type)
        chunks = await chunker.chunk(parsed)
        texts = [c.content for c in chunks]
        embeddings = await embedding_service.embed_batch(texts)
        await milvus_indexer.index_chunks(kb_id, document_id, chunks, embeddings)
        return len(embeddings)

    try:
        loop = asyncio.get_event_loop()
        chunk_count = loop.run_until_complete(_process())
        return {"status": "ready", "chunk_count": chunk_count}
    except Exception as e:
        raise self.retry(exc=e, countdown=60)
