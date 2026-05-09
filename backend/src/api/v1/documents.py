from fastapi import APIRouter, UploadFile, File, Form

from src.api.deps import DBSession
from src.schemas.document import DocumentResponse, DocumentList

router = APIRouter()


@router.get("/kb/{kb_id}", response_model=DocumentList)
async def list_documents(kb_id: str, db: DBSession):
    """List all documents in a knowledge base."""
    ...


@router.post("/upload", response_model=DocumentResponse, status_code=202)
async def upload_document(
    kb_id: str = Form(...),
    file: UploadFile = File(...),
    db: DBSession = None,
):
    """Upload a document to a knowledge base. Processing happens asynchronously."""
    ...


@router.get("/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: DBSession):
    """Get document details and processing status."""
    ...


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, db: DBSession):
    """Delete a document and its chunks."""
    ...
