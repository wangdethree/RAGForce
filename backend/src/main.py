"""RAGForce - 企业级 RAG 平台"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1.router import api_router
from core.config import settings
from core.exceptions import register_exception_handlers
from core.logging import setup_logging
from middleware.audit import AuditMiddleware
from middleware.metrics import MetricsMiddleware, metrics_endpoint
from models import KnowledgeBase, Document, DocumentChunk, AuditLog  # noqa: F401 注册所有模型

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)
app.add_middleware(AuditMiddleware)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


@app.get("/metrics")
async def metrics():
    return await metrics_endpoint()
