from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AgentCreate(BaseModel):
    name: str = Field(..., max_length=255)
    domain: str = Field(..., max_length=255)
    objective: str
    status: str = Field(default="active", pattern=r"^(active|paused)$")


class AgentUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    domain: str | None = Field(None, max_length=255)
    objective: str | None = None
    status: str | None = Field(None, pattern=r"^(active|paused|error)$")


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    name: str
    domain: str
    objective: str
    status: str
    created_by: UUID
    created_at: datetime
