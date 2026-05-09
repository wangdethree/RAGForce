from pymilvus import Collection, connections, utility

from src.core.config import settings
from src.schemas.ingestion import Chunk


class MilvusIndexer:
    """Index document chunks into Milvus."""

    def __init__(self):
        self._connected = False

    def connect(self):
        if not self._connected:
            connections.connect(
                alias="default",
                host=settings.MILVUS_HOST,
                port=settings.MILVUS_PORT,
            )
            self._connected = True

    def ensure_collection(self):
        self.connect()
        if not utility.has_collection(settings.MILVUS_COLLECTION_NAME):
            from pymilvus import CollectionSchema, DataType, FieldSchema

            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=100, is_primary=True),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024),
                FieldSchema(name="kb_id", dtype=DataType.VARCHAR, max_length=36),
                FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=36),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=4096),
                FieldSchema(name="content_type", dtype=DataType.VARCHAR, max_length=20),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
            ]
            schema = CollectionSchema(fields, description="RAGForce document chunks")
            collection = Collection(name=settings.MILVUS_COLLECTION_NAME, schema=schema)

            index_params = {
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            }
            collection.create_index(field_name="embedding", index_params=index_params)
            collection.load()

    async def index_chunks(
        self,
        kb_id: str,
        document_id: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ):
        self.ensure_collection()
        collection = Collection(name=settings.MILVUS_COLLECTION_NAME)

        entities = []
        for chunk, embedding in zip(chunks, embeddings):
            entities.append({
                "id": f"{document_id}_{chunk.index}",
                "embedding": embedding,
                "kb_id": kb_id,
                "document_id": document_id,
                "content": chunk.content[:4096],
                "content_type": chunk.content_type,
                "chunk_index": chunk.index,
            })

        collection.insert(entities)
        collection.flush()


milvus_indexer = MilvusIndexer()
