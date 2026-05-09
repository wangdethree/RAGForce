from fastapi import APIRouter

from src.api.v1 import knowledge_base, documents, retrieval, chat, audit, dashboard

api_router = APIRouter()

api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_router.include_router(knowledge_base.router, prefix="/knowledge-bases", tags=["Knowledge Bases"])
api_router.include_router(documents.router, prefix="/documents", tags=["Documents"])
api_router.include_router(retrieval.router, prefix="/retrieval", tags=["Retrieval"])
api_router.include_router(chat.router, prefix="/chat", tags=["Chat"])
api_router.include_router(audit.router, prefix="/audit-logs", tags=["Audit Logs"])
