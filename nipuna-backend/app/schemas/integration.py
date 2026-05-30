from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IntegrationConnectRequest(BaseModel):
    config: dict = Field(default_factory=dict)


class IntegrationInitializeRequest(BaseModel):
    provider: str


class IntegrationResponse(BaseModel):
 
    model_config = ConfigDict(from_attributes=True)
 
    id: UUID
    org_id: UUID
    display_name: str
    description: str | None = None
    provider: str
    status: str
    category: str | None = None
    sync_health: int
    last_synced: datetime | None = None


class IntegrationListResponse(BaseModel):
    connected: int
    pending: int
    sync_health: int
    integrations: list[IntegrationResponse]


class AvailableIntegrationResponse(BaseModel):
    provider: str
    display_name: str
    description: str | None = None
    category: str | None = None

