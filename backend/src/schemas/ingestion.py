from pydantic import BaseModel


class ImageBlock(BaseModel):
    page_num: int
    index: int
    image_bytes: bytes
    ext: str

    model_config = {"arbitrary_types_allowed": True}


class ParsedDocument(BaseModel):
    text: str
    pages: list[dict]
    images: list[ImageBlock]
    tables: list[dict]


class Chunk(BaseModel):
    index: int
    content: str
    content_type: str = "text"
    metadata: dict = {}
