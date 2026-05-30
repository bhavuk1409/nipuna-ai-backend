from pydantic import BaseModel, Field


class WorkspaceResponse(BaseModel):
    name: str


class WorkspaceUpdate(BaseModel):
    name: str = Field(..., max_length=255)


class PreferencesResponse(BaseModel):
    approval_required: bool
    digest_time: str
    escalation_window: int


class PreferencesUpdate(BaseModel):
    approval_required: bool = True
    digest_time: str = Field(default="09:00", max_length=16)
    escalation_window: int = Field(default=24, ge=1, le=168)
