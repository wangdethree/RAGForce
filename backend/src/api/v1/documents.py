from fastapi import APIRouter, UploadFile, File, Form

from src.api.deps import DBSession
from src.schemas.document import DocumentResponse, DocumentList

router = APIRouter()


@router.get("/kb/{kb_id}", response_model=DocumentList)
async def list_documents(kb_id: str, db: DBSession):
    """获取知识库中的所有文档列表"""
    ...


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    db: DBSession = None,
):
    """上传文档到知识库，处理过程异步执行"""
    ...


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DBSession):
    """获取文档详情和处理状态"""
    ...


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, db: DBSession):
    """删除文档及其所有分块"""
    ...
