from datetime import datetime

from pydantic import BaseModel


class AuditLogResponse(BaseModel):
    id: str
    action: str
    resource_type: str
    resource_id: str
    detail: dict
    ip_address: str
    duration_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogList(BaseModel):
    items: list[AuditLogResponse]
    total: int
