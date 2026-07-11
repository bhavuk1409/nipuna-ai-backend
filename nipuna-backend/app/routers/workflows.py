from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.organization import Organization
from app.models.user import User
from app.models.workflow import Workflow, WorkflowExecution
from app.schemas.workflow import (
    NodeTestRequest,
    NodeTestResponse,
    WorkflowCreate,
    WorkflowExecutionItem,
    WorkflowExecutionResponse,
    WorkflowResponse,
    WorkflowResumeRequest,
    WorkflowRunResponse,
    WorkflowUpdate,
)
from app.services.workflow_engine import run_workflow as run_workflow_engine
from app.services.workflow_engine.engine import resume_from_approval
from app.services.workflow_engine.handlers import get_handler
from app.services.workflow_engine.param_adapter import normalize
from app.services.workflow_engine.templating import resolve
from app.utils.audit import log_action

router = APIRouter(prefix="/workflows", tags=["workflows"])


def _timestamp_label(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


def _workflow_response(workflow: Workflow) -> WorkflowResponse:
    return WorkflowResponse.model_validate(workflow)


def _ensure_webhook_token(workflow: Workflow) -> str:
    """Lazily assigns a stable secret token used to trigger this workflow
    externally via POST /workflows/{id}/trigger?token=... (webhook-style nodes)."""
    metadata = dict(workflow.metadata_json or {})
    token = metadata.get("webhook_token")
    if not token:
        token = secrets.token_urlsafe(24)
        metadata["webhook_token"] = token
        workflow.metadata_json = metadata
    return token


def _has_webhook_trigger(workflow: Workflow) -> bool:
    return any(str((n.get("data") or {}).get("type")) == "webhook" for n in (workflow.nodes or []))


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
    webhook_token = _ensure_webhook_token(workflow)
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_activated",
        metadata={"workflow_id": str(workflow.id)},
    )
    await db.commit()
    return WorkflowRunResponse(
        status="active",
        message="Workflow activated",
        engine_synced=True,
        detail=f"Webhook trigger URL token: {webhook_token}" if _has_webhook_trigger(workflow) else None,
    )


@router.post("/{workflow_id}/deactivate", response_model=WorkflowRunResponse)
async def deactivate_workflow(
    workflow_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    workflow.status = "inactive"
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_deactivated",
        metadata={"workflow_id": str(workflow.id)},
    )
    await db.commit()
    return WorkflowRunResponse(status="inactive", message="Workflow deactivated", engine_synced=True)


async def _execute_and_record(
    workflow: Workflow,
    org_id: UUID,
    db: AsyncSession,
    mode: str,
    dry_run: bool = False,
) -> WorkflowExecution:
    """Runs the Nipuna workflow engine and persists a WorkflowExecution row.

    `dry_run=True` makes the engine skip real external side effects
    (Gmail / Slack / Tally / Composio calls, etc.) and instead return a
    synthetic "would have called X" stub for each integration node.
    """
    result = await run_workflow_engine(workflow, str(org_id), db, dry_run=dry_run)

    workflow.last_run_at = result.stopped_at
    workflow.last_run_status = result.status

    execution = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=org_id,
        status=result.status,
        mode=mode,
        started_at=result.started_at,
        stopped_at=result.stopped_at,
        duration_ms=result.duration_ms,
        timeline=result.timeline,
        input_json=result.input,
        output_json=result.output,
        logs=result.logs,
    )
    db.add(execution)
    return execution


@router.post("/{workflow_id}/run", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_id: UUID,
    dry_run: bool = Query(
        default=False,
        description="If true, the engine walks the graph but does not call any external services. Used by the Test button.",
    ),
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    mode = "test:dry_run" if dry_run else "manual"
    execution = await _execute_and_record(workflow, org.id, db, mode=mode, dry_run=dry_run)

    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_tested",
        metadata={"workflow_id": str(workflow.id), "status": execution.status, "dry_run": dry_run},
    )
    await db.commit()
    await db.refresh(execution)

    message = {
        "success": (
            "Workflow test completed (dry run) — no external services were called"
            if dry_run
            else "Workflow test completed successfully"
        ),
        "error": "Workflow test failed",
        "waiting_approval": "Workflow is waiting for human approval",
    }.get(execution.status, "Workflow test finished")

    return WorkflowRunResponse(
        execution_id=str(execution.id),
        status=execution.status,
        message=message,
        engine_synced=True,
        detail=(execution.output_json or {}).get("error"),
    )


@router.post("/{workflow_id}/trigger", response_model=WorkflowRunResponse, include_in_schema=False)
async def trigger_workflow_webhook(
    workflow_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    """Public webhook entrypoint for `webhook`-trigger workflows — no user
    auth (external services call this), protected by the per-workflow token
    generated in `activate_workflow`.
    """
    result = await db.execute(
        select(Workflow).where(Workflow.id == workflow_id, Workflow.status == "active")
    )
    workflow = result.scalar_one_or_none()
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found or inactive")

    expected_token = (workflow.metadata_json or {}).get("webhook_token")
    if not expected_token or not secrets.compare_digest(token, expected_token):
        raise HTTPException(status_code=403, detail="Invalid webhook token")

    execution = await _execute_and_record(workflow, workflow.org_id, db, mode="webhook")
    await db.commit()
    await db.refresh(execution)

    return WorkflowRunResponse(
        execution_id=str(execution.id),
        status=execution.status,
        message="Workflow triggered via webhook",
        engine_synced=True,
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
            }
            for execution in executions
        ],
        engine_synced=True,
    )


@router.get(
    "/{workflow_id}/executions/{execution_id}",
    response_model=WorkflowExecutionItem,
)
async def get_execution(
    workflow_id: UUID,
    execution_id: UUID,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowExecutionItem:
    """Fetch a single execution's current state. Used by the frontend for
    live polling while a workflow is running or paused on approval."""
    workflow = await _get_workflow_or_404(workflow_id, org, db)
    result = await db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.id == execution_id,
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.org_id == org.id,
        )
    )
    execution = result.scalar_one_or_none()
    if execution is None:
        raise HTTPException(status_code=404, detail="Execution not found")
    return WorkflowExecutionItem(
        id=execution.id,
        workflow_id=execution.workflow_id,
        status=execution.status,
        mode=execution.mode,
        started_at=execution.started_at,
        stopped_at=execution.stopped_at,
        duration_ms=execution.duration_ms,
        timeline=execution.timeline or [],
        input=execution.input_json or {},
        output=execution.output_json or {},
        logs=execution.logs or [],
    )


@router.post("/{workflow_id}/resume", response_model=WorkflowRunResponse)
async def resume_workflow(
    workflow_id: UUID,
    body: WorkflowResumeRequest,
    dry_run: bool = Query(
        default=False,
        description="If true, downstream integration calls return synthetic stubs instead of firing real services. Used by the Test button's Approve/Reject action.",
    ),
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> WorkflowRunResponse:
    """Resume a workflow paused on a `waiting_approval` node.

    Loads the original execution, verifies it belongs to this workflow/org
    and is still waiting, then runs the engine from the approval node
    forward with the decision injected into the context. Persists the
    resumed result as a new execution row.
    """
    workflow = await _get_workflow_or_404(workflow_id, org, db)

    original = await db.execute(
        select(WorkflowExecution).where(
            WorkflowExecution.id == body.execution_id,
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.org_id == org.id,
        )
    )
    orig_execution = original.scalar_one_or_none()
    if orig_execution is None:
        raise HTTPException(status_code=404, detail="Paused execution not found")
    if orig_execution.status != "waiting_approval":
        raise HTTPException(
            status_code=409,
            detail=f"Execution is not waiting for approval (current status: {orig_execution.status})",
        )

    # Find the approval node in the workflow graph. There can be at most one
    # in the paused timeline (the engine halts on the first waiting_approval).
    approval_node = None
    for n in workflow.nodes or []:
        if (n.get("data") or {}).get("type") == "approval":
            approval_node = n
            break
    if approval_node is None:
        raise HTTPException(
            status_code=409,
            detail="Workflow no longer contains the approval node it was paused on.",
        )

    approval_title = str(approval_node.get("data", {}).get("title") or approval_node.get("id"))
    prior_context = dict(orig_execution.output_json or {}).get("results") or {}

    # The original execution was paused *after* the approval node had been
    # "executed" in the engine (it produced a `waiting_approval` result). We
    # pass the original node_outputs into the resume so downstream nodes can
    # template `{{ <approval title>.decision }}` correctly. We layer the
    # decision on top in resume_from_approval.
    result = await resume_from_approval(
        nodes=workflow.nodes or [],
        edges=workflow.edges or [],
        org_id=str(org.id),
        db=db,
        approval_node_id=str(approval_node.get("id")),
        approval_title=approval_title,
        decision=body.decision,
        approver_note=body.approver_note,
        prior_context=prior_context,
        dry_run=dry_run,
    )

    # Persist the resumed portion as a new execution row (audit trail —
    # the original paused row stays as-is for history).
    workflow.last_run_at = result.stopped_at
    workflow.last_run_status = result.status

    new_execution = WorkflowExecution(
        workflow_id=workflow.id,
        org_id=org.id,
        status=result.status,
        mode=f"resume:{body.decision}",
        started_at=result.started_at,
        stopped_at=result.stopped_at,
        duration_ms=result.duration_ms,
        timeline=result.timeline,
        input_json={"resumed_from": str(orig_execution.id), "decision": body.decision},
        output_json=result.output,
        logs=result.logs,
    )
    db.add(new_execution)

    # Mark the original execution as resolved (no longer waiting).
    orig_execution.status = f"resolved:{body.decision}"

    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_resumed",
        metadata={
            "workflow_id": str(workflow.id),
            "execution_id": str(orig_execution.id),
            "new_execution_id": None,  # filled in after flush
            "decision": body.decision,
            "dry_run": dry_run,
        },
    )
    await db.commit()
    await db.refresh(new_execution)

    message = {
        "success": "Workflow resumed and completed",
        "error": "Resumed workflow failed",
        "waiting_approval": "Resumed workflow hit another approval checkpoint",
    }.get(result.status, "Resumed workflow finished")

    return WorkflowRunResponse(
        execution_id=str(new_execution.id),
        status=result.status,
        message=message,
        engine_synced=True,
        detail=(result.output or {}).get("error"),
    )


@router.post(
    "/{workflow_id}/nodes/{node_id}/test",
    response_model=NodeTestResponse,
)
async def test_node(
    workflow_id: UUID,
    node_id: str,
    body: NodeTestRequest | None = None,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NodeTestResponse:
    """Run a single node in isolation (always in dry-run mode).

    The node is looked up inside the saved workflow's `nodes` list by id.
    The node's handler is invoked with an empty upstream context, plus
    the user-supplied `test_input` injected under the special `input`
    key — so `{{ input.foo }}` placeholders inside the node's parameters
    resolve to the test fixtures. This is the per-node equivalent of the
    "Test Workflow" dry-run, scoped to one node and skipping real
    side effects.

    Note: the workflow is NOT mutated. The test runs against the
    currently-saved graph, so callers should `PUT /workflows/{id}`
    first if they want to test unsaved changes.
    """
    workflow = await _get_workflow_or_404(workflow_id, org, db)

    target_node = None
    for n in workflow.nodes or []:
        if str(n.get("id")) == str(node_id):
            target_node = n
            break
    if target_node is None:
        raise HTTPException(
            status_code=404,
            detail=f"Node '{node_id}' not found in workflow",
        )

    node_data = target_node.get("data") or {}
    node_type = str(node_data.get("type") or "").strip() or "unknown"
    node_title = str(node_data.get("title") or node_id)

    test_input = (body.test_input if body else {}) or {}
    if not isinstance(test_input, dict):
        raise HTTPException(
            status_code=422,
            detail="`test_input` must be a JSON object",
        )

    # The test context is empty upstream + the user's test_input available
    # under `input` (so `{{ input.foo }}` resolves) and also flattened up
    # one level under `input.<key>` (so `{{ input }}` returns the whole
    # dict, matching the engine's `.output` transparency convention).
    context: dict[str, Any] = {
        "input": {
            "status": "success",
            "output": test_input,
            **({"raw": test_input} if test_input else {}),
        }
    }

    # Normalize the node's friendly fields → engine params, then resolve
    # any `{{ ... }}` placeholders against the test context.
    normalized_params = normalize(target_node)
    try:
        resolved_params = resolve(normalized_params, context)
    except Exception:  # noqa: BLE001
        # Templating failure is non-fatal — surface the unresolved params
        # so the user can see exactly which placeholder tripped.
        resolved_params = normalized_params

    handler = get_handler(node_type)
    started_at = datetime.now(timezone.utc)
    log_lines: list[str] = [
        f"[{started_at.strftime('%H:%M:%S UTC')}] Testing '{node_title}' ({node_type}) in dry-run mode.",
    ]
    result: dict[str, Any] = {"status": "error", "error": "Handler produced no result"}
    try:
        result = await handler(target_node, resolved_params, str(org.id), db, dry_run=True)
    except Exception as exc:  # noqa: BLE001
        result = {"status": "error", "error": str(exc)}
    stopped_at = datetime.now(timezone.utc)
    duration_ms = max(1, int((stopped_at - started_at).total_seconds() * 1000))

    log_lines.append(
        f"[{stopped_at.strftime('%H:%M:%S UTC')}] "
        f"Node finished with status '{result.get('status', 'unknown')}' in {duration_ms}ms."
    )

    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="workflow_node_tested",
        metadata={
            "workflow_id": str(workflow.id),
            "node_id": str(node_id),
            "node_type": node_type,
            "status": str(result.get("status", "unknown")),
        },
    )
    await db.commit()

    return NodeTestResponse(
        node_id=str(node_id),
        node_type=node_type,
        node_title=node_title,
        status=str(result.get("status", "unknown")),
        output=result,
        logs=log_lines,
        duration_ms=duration_ms,
        resolved_params=resolved_params,
    )
