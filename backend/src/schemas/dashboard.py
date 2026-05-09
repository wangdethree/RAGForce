from pydantic import BaseModel


class DashboardStats(BaseModel):
    kb_count: int = 0
    document_count: int = 0
    chunk_count: int = 0
    audit_log_count: int = 0


class RecentKB(BaseModel):
    id: str
    name: str
    document_count: int
    created_at: str
