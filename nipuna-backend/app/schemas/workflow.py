from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkflowBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    status: str = Field(default="inactive", pattern=r"^(active|inactive)$")
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowCreate(WorkflowBase):
    pass


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    status: str | None = Field(None, pattern=r"^(active|inactive)$")
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    org_id: UUID
    name: str
    description: str
    status: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    metadata: dict[str, Any] = Field(validation_alias="metadata_json", serialization_alias="metadata")
    n8n_workflow_id: str | None
    last_run_at: datetime | None
    last_run_status: str | None
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


class WorkflowRunResponse(BaseModel):
    execution_id: str | None = None
    status: str
    message: str
    n8n_synced: bool = False
    detail: str | None = None


class WorkflowExecutionItem(BaseModel):
    id: UUID | str
    workflow_id: UUID | str
    status: str
    mode: str
    started_at: datetime
    stopped_at: datetime | None
    duration_ms: int | None
    timeline: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    n8n_execution_id: str | None = None


class WorkflowExecutionResponse(BaseModel):
    executions: list[WorkflowExecutionItem | dict[str, Any]]
    n8n_synced: bool = False
    detail: str | None = None
