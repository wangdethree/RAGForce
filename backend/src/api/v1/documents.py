import os
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form
from sqlalchemy import select

from api.deps import DBSession
from core.config import settings
from core.exceptions import NotFoundError, InvalidOperationError
from models.document import Document, DocumentStatus
from schemas.document import DocumentResponse, DocumentList

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

router = APIRouter()


def _get_extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


@router.get("/kb/{kb_id}", response_model=DocumentList)
async def list_documents(kb_id: str, db: DBSession):
    """获取知识库中的所有文档列表"""
    result = await db.execute(
        select(Document)
        .where(Document.kb_id == kb_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return DocumentList(items=list(docs), total=len(docs))


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    db: DBSession = None,
):
    """上传文档到知识库，处理过程异步执行"""
    ext = _get_extension(file.filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidOperationError(f"不支持的文件类型: {ext}，仅支持 PDF、DOCX、DOC")

    upload_dir = Path(settings.UPLOAD_DIR) / kb_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    storage_name = f"{uuid.uuid4().hex}{ext}"
    storage_path = upload_dir / storage_name

    content = await file.read()
    with open(storage_path, "wb") as f:
        f.write(content)

    doc = Document(
        kb_id=kb_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        file_size=len(content),
        storage_path=str(storage_path),
        status=DocumentStatus.UPLOADED,
    )
    db.add(doc)
    await db.flush()
    await db.refresh(doc)

    # 触发异步处理（Celery 不可用时跳过）
    try:
        from worker.doc_processing import process_document
        process_document.delay(doc.id, kb_id, str(storage_path), ext.lstrip("."))
    except Exception:
        pass

    return doc


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DBSession):
    """获取文档详情和处理状态"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("文档", doc_id)
    return doc


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, db: DBSession):
    """删除文档及其所有分块"""
    result = await db.execute(select(Document).where(Document.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("文档", doc_id)

    # 删除物理文件
    if doc.storage_path and os.path.exists(doc.storage_path):
        os.remove(doc.storage_path)

    await db.delete(doc)
