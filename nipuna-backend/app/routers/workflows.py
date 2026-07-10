from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowExecutionResponse,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowUpdate,
)
from app.utils.audit import log_action

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _timestamp_label(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


def _workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse.model_validate(workflow)


def _n8n_headers() -> dict[str, str]:
    settings = get_settings()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if settings.n8n_api_key:
        headers["X-N8N-API-KEY"] = settings.n8n_api_key
    return headers


async def _n8n_request(method: str, path: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    base_url = settings.n8n_base_url.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.n8n_timeout_seconds) as client:
        response = await client.request(method, f"{base_url}/api/v1{path}", headers=_n8n_headers(), json=json)
    response.raise_for_status()
    if response.status_code == 204 or not response.content:
        return {}
    return response.json()


def _n8n_payload(workflow: Workflow) -> dict[str, Any]:
    return {
        "name": workflow.name,
        "active": workflow.status == "active",
        "nodes": workflow.metadata_json.get("n8nNodes", workflow.nodes),
        "connections": workflow.metadata_json.get("n8nConnections", {}),
        "settings": workflow.metadata_json.get("n8nSettings", {"executionOrder": "v1"}),
    }


def _ordered_nodes(workflow: Workflow) -> list[dict[str, Any]]:
    nodes = workflow.nodes or []
    if not nodes:
        return []

    by_id = {str(node.get("id")): node for node in nodes}
    targets = {str(edge.get("target")) for edge in workflow.edges or [] if edge.get("target")}
    start = next((node for node in nodes if str(node.get("id")) not in targets), nodes[0])

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = start
    while current:
        node_id = str(current.get("id"))
        if node_id in seen:
            break
        ordered.append(current)
        seen.add(node_id)
        next_edge = next((edge for edge in workflow.edges or [] if str(edge.get("source")) == node_id), None)
        current = by_id.get(str(next_edge.get("target"))) if next_edge else None

    for node in nodes:
        node_id = str(node.get("id"))
        if node_id not in seen:
            ordered.append(node)

    return ordered


def _node_title(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    return str(data.get("title") or node.get("name") or node.get("id") or "Node")


def _simulate_execution_payload(workflow: Workflow, started_at: datetime) -> dict[str, Any]:
    ordered_nodes = _ordered_nodes(workflow)
    timeline = ["Workflow Started", *[_node_title(node) for node in ordered_nodes], "Completed"]
    logs = [f"[{_timestamp_label(started_at)}] Workflow started in Nipuna test runner."]

    for index, node in enumerate(ordered_nodes, start=1):
        data = node.get("data") or {}
        node_type = data.get("type") or "node"
        logs.append(f"[{_timestamp_label(started_at)}] Step {index}: {_node_title(node)} ({node_type}) completed.")

    stopped_at = datetime.now(timezone.utc)
    duration_ms = max(1, int((stopped_at - started_at).total_seconds() * 1000))
    output = {
        "status": "success",
        "workflow_id": str(workflow.id),
        "workflow_name": workflow.name,
        "steps_executed": len(ordered_nodes),
        "mode": "local",
    }
    input_payload = {
        "trigger": _node_title(ordered_nodes[0]) if ordered_nodes else "Manual Test",
        "workflow_id": str(workflow.id),
        "workflow_name": workflow.name,
    }
    logs.append(f"[{_timestamp_label(stopped_at)}] Workflow execution finished successfully.")

    return {
        "status": "success",
        "started_at": started_at,
        "stopped_at": stopped_at,
        "duration_ms": duration_ms,
        "timeline": timeline,
        "input": input_payload,
        "output": output,
        "logs": logs,
    }


async def _sync_to_n8n(workflow: Workflow) -> tuple[bool, str | None]:
    settings = get_settings()
    if not settings.n8n_api_key:
        return False, "N8N_API_KEY is not configured"

    try:
        payload = _n8n_payload(workflow)
        if workflow.n8n_workflow_id:
            await _n8n_request("PUT", f"/workflows/{workflow.n8n_workflow_id}", payload)
        else:
            created = await _n8n_request("POST", "/workflows", payload)
            workflow.n8n_workflow_id = str(created.get("id") or created.get("data", {}).get("id") or "")
        if workflow.n8n_workflow_id:
            action = "activate" if workflow.status == "active" else "deactivate"
            await _n8n_request("POST", f"/workflows/{workflow.n8n_workflow_id}/{action}")
        return True, None
    except (httpx.HTTPError, RuntimeError) as exc:
        return False, str(exc)


async def _get_workflow_or_404(workflow_id: UUID, org: Organization, db: AsyncSession) -> Workflow:
    result = await db.execute(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.org_id == org.id,
            Workflow.status != "deleted",
        )
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.get("", response_model=dict[str, list[WorkflowResponse]])
async def list_workflows(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[WorkflowResponse]]:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.org_id == org.id, Workflow.status != "deleted")
        .order_by(Workflow.updated_at.desc())
    )
    workflows = result.scalars().all()
    return {"workflows": [_workflow_response(workflow) for workflow in workflows]}


@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = Workflow(
        org_id=org.id,
        name=body.name,
        description=body.description,
        status=body.status,
        nodes=body.nodes,
        edges=body.edges,
        metadata_json=body.metadata,
        created_by=user.id,
    )
    db.add(workflow)
    await db.flush()
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_created",
        metadata={"workflow_id": str(workflow.id), "name": workflow.name},
    )
    await db.commit()
    await db.refresh(workflow)
    return _workflow_response(workflow)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    return _workflow_response(workflow)


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
    workflow_id: UUID,
    body: WorkflowUpdate,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    update_data = body.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_json"] = update_data.pop("metadata")
    for field, value in update_data.items():
        setattr(workflow, field, value)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_updated",
        metadata={"workflow_id": str(workflow.id), "name": workflow.name},
    )
    await db.commit()
    await db.refresh(workflow)
    return _workflow_response(workflow)


@router.delete("/{workflow_id}", response_model=dict[str, str])
async def delete_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    workflow.status = "deleted"
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_deleted",
        metadata={"workflow_id": str(workflow.id), "name": workflow.name},
    )
    await db.commit()
    return {"status": "deleted"}


@router.post("/{workflow_id}/activate", response_model=WorkflowRunResponse)
async def activate_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    workflow.status = "active"
    synced, detail = await _sync_to_n8n(workflow)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_activated",
        metadata={"workflow_id": str(workflow.id), "n8n_synced": synced, "detail": detail},
    )
    await db.commit()
    return WorkflowRunResponse(status="active", message="Workflow activated", n8n_synced=synced, detail=detail)


@router.post("/{workflow_id}/deactivate", response_model=WorkflowRunResponse)
async def deactivate_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    workflow.status = "inactive"
    synced, detail = await _sync_to_n8n(workflow)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_deactivated",
        metadata={"workflow_id": str(workflow.id), "n8n_synced": synced, "detail": detail},
    )
    await db.commit()
    return WorkflowRunResponse(status="inactive", message="Workflow deactivated", n8n_synced=synced, detail=detail)


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    started_at = datetime.now(timezone.utc)
    workflow.last_run_at = started_at

    if workflow.n8n_workflow_id and get_settings().n8n_api_key:
        try:
            response = await _n8n_request("POST", f"/workflows/{workflow.n8n_workflow_id}/run")
            workflow.last_run_status = "running"
            execution = WorkflowExecution(
                workflow_id=workflow.id,
                org_id=org.id,
                status="running",
                mode="n8n",
                started_at=started_at,
                stopped_at=None,
                duration_ms=None,
                timeline=["Workflow Started"],
                input_json={"workflow_id": str(workflow.id), "n8n_workflow_id": workflow.n8n_workflow_id},
                output_json=response,
                logs=[f"[{_timestamp_label(started_at)}] Workflow test started in n8n."],
                n8n_execution_id=str(response.get("executionId") or response.get("id") or ""),
            )
            db.add(execution)
            await db.commit()
            await db.refresh(execution)
            return WorkflowRunResponse(
                execution_id=str(execution.id),
                status="running",
                message="Workflow test started in n8n",
                n8n_synced=True,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            workflow.last_run_status = "error"
            stopped_at = datetime.now(timezone.utc)
            execution = WorkflowExecution(
                workflow_id=workflow.id,
                org_id=org.id,
                status="error",
                mode="n8n",
                started_at=started_at,
                stopped_at=stopped_at,
                duration_ms=max(1, int((stopped_at - started_at).total_seconds() * 1000)),
                timeline=["Workflow Started", "n8n Error"],
                input_json={"workflow_id": str(workflow.id), "n8n_workflow_id": workflow.n8n_workflow_id},
                output_json={"status": "error", "error_message": str(exc)},
                logs=[
                    f"[{_timestamp_label(started_at)}] Workflow test started in n8n.",
                    f"[{_timestamp_label(stopped_at)}] [ERROR] {exc}",
                ],
            )
            db.add(execution)
            await db.commit()
            return WorkflowRunResponse(
                status="error",
                message="Workflow test could not start in n8n",
                n8n_synced=False,
                detail=str(exc),
            )

    simulated = _simulate_execution_payload(workflow, started_at)
    workflow.last_run_at = simulated["stopped_at"]
    workflow.last_run_status = "success"
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=org.id,
        status=simulated["status"],
        mode="local",
        started_at=simulated["started_at"],
        stopped_at=simulated["stopped_at"],
        duration_ms=simulated["duration_ms"],
        timeline=simulated["timeline"],
        input_json=simulated["input"],
        output_json=simulated["output"],
        logs=simulated["logs"],
    )
    db.add(execution)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_tested",
        metadata={"workflow_id": str(workflow.id), "mode": "local"},
    )
    await db.commit()
    await db.refresh(execution)
    return WorkflowRunResponse(
        execution_id=str(execution.id),
        status="success",
        message="Workflow test completed locally",
        n8n_synced=False,
        detail="Configure N8N_API_KEY to run this workflow in n8n.",
    )


@router.get("/{workflow_id}/executions", response_model=WorkflowExecutionResponse)
async def list_executions(
    workflow_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExecutionResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    if workflow.n8n_workflow_id and get_settings().n8n_api_key:
        try:
            response = await _n8n_request(
                "GET",
                f"/executions?workflowId={workflow.n8n_workflow_id}&limit={limit}&includeData=true",
            )
            return WorkflowExecutionResponse(
                executions=response.get("data") or response.get("results") or [],
                n8n_synced=True,
            )
        except (httpx.HTTPError, RuntimeError) as exc:
            return WorkflowExecutionResponse(executions=[], n8n_synced=False, detail=str(exc))

    result = await db.execute(
        select(WorkflowExecution)
        .where(
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.org_id == org.id,
        )
        .order_by(WorkflowExecution.started_at.desc())
        .limit(limit)
    )
    executions = result.scalars().all()
    return WorkflowExecutionResponse(
        executions=[
            {
                "id": execution.id,
                "workflow_id": execution.workflow_id,
                "status": execution.status,
                "mode": execution.mode,
                "started_at": execution.started_at,
                "stopped_at": execution.stopped_at,
                "duration_ms": execution.duration_ms,
                "timeline": execution.timeline,
                "input": execution.input_json,
                "output": execution.output_json,
                "logs": execution.logs,
                "n8n_execution_id": execution.n8n_execution_id,
            }
            for execution in executions
        ],
        n8n_synced=False,
    )
