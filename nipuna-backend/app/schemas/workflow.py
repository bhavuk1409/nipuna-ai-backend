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
    engine_synced: bool = False
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
    engine_synced: bool = False
    detail: str | None = None


class WorkflowResumeRequest(BaseModel):
    """Body for POST /workflows/{id}/resume — human decision on a paused approval node."""

    execution_id: UUID
    decision: str = Field(..., pattern=r"^(approve|reject)$")
    approver_note: str | None = None


class NodeTestRequest(BaseModel):
    """Body for POST /workflows/{id}/nodes/{node_id}/test — run a single node
    in isolation. `test_input` is a user-supplied context dictionary that
    is injected into the engine's templating context under the special
    `input` key, so `{{ input.foo }}` references inside the node's
    parameters resolve to the user's test fixtures. The rest of the
    templating context is empty (no upstream nodes).
    """

    test_input: dict[str, Any] = Field(default_factory=dict)


class NodeTestResponse(BaseModel):
    """Result of a single-node test. Mirrors the shape of the engine's
    `ExecutionResult` but scoped to one node: status, the handler's
    returned dict, the duration in ms, and the list of log lines."""

    node_id: str
    node_type: str
    node_title: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    resolved_params: dict[str, Any] = Field(default_factory=dict)
