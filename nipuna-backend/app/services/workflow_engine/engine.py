"""Core DAG execution engine for Nipuna workflows.

Walks the same nodes/edges graph the frontend canvas edits directly
(no format conversion, no external process) — starting from nodes with
no incoming edge, following `edges` in order, branching on IF node
`sourceHandle` ("true"/"false"), and stopping a branch when it hits an
`approval` node awaiting a human decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workflow_engine.handlers import get_handler
from app.services.workflow_engine.param_adapter import normalize
from app.services.workflow_engine.templating import resolve

if TYPE_CHECKING:
    from app.models.workflow import Workflow


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ts(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


@dataclass
class ExecutionResult:
    status: str  # "success" | "error" | "waiting_approval"
    started_at: datetime
    stopped_at: datetime
    duration_ms: int
    timeline: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    node_outputs: dict[str, Any] = field(default_factory=dict)
    input: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class NipunaWorkflowEngine:
    """Stateless — call `run()` with a workflow's nodes/edges each time."""

    async def run(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        org_id: str,
        db: AsyncSession,
        dry_run: bool = False,
    ) -> ExecutionResult:
        started_at = _now()
        timeline: list[str] = ["Workflow Started"]
        logs: list[str] = [f"[{_ts(started_at)}] Workflow started{' (dry run)' if dry_run else ''}."]
        context: dict[str, Any] = {}  # node title -> output

        if not nodes:
            stopped_at = _now()
            return ExecutionResult(
                status="success",
                started_at=started_at,
                stopped_at=stopped_at,
                duration_ms=1,
                timeline=["Workflow Started", "Nothing to run", "Completed"],
                logs=logs + ["No nodes in this workflow."],
                input={},
                output={"message": "Empty workflow — nothing to execute."},
            )

        by_id = {str(n["id"]): n for n in nodes}
        targets = {str(e["target"]) for e in edges if e.get("target")}
        start_nodes = [n for n in nodes if str(n["id"]) not in targets] or [nodes[0]]

        # Adjacency: node_id -> list of (edge, target_node)
        outgoing: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            outgoing.setdefault(str(e["source"]), []).append(e)

        visited: set[str] = set()
        queue: list[str] = [str(n["id"]) for n in start_nodes]
        first_input = self._node_params(start_nodes[0]) if start_nodes else {}
        status = "success"
        error: str | None = None

        try:
            while queue:
                node_id = queue.pop(0)
                if node_id in visited or node_id not in by_id:
                    continue
                visited.add(node_id)
                node = by_id[node_id]
                title = str(node.get("data", {}).get("title") or node_id)
                node_type = str(node.get("data", {}).get("type", "unknown"))

                params = resolve(self._node_params(node), context)
                handler = get_handler(node_type)

                logs.append(f"[{_ts(_now())}] Running '{title}' ({node_type})...")
                result = await handler(node, params, org_id, db, dry_run=dry_run)
                context[title] = result
                timeline.append(title)

                if result.get("status") == "error":
                    status = "error"
                    error = str(result.get("error") or result.get("reason") or "Node failed")
                    logs.append(f"[{_ts(_now())}] [ERROR] '{title}': {error}")
                    break

                if result.get("status") == "waiting_approval":
                    status = "waiting_approval"
                    logs.append(f"[{_ts(_now())}] '{title}' is waiting for human approval — pausing here.")
                    break

                logs.append(f"[{_ts(_now())}] '{title}' completed.")

                next_edges = outgoing.get(node_id, [])
                if node_type == "if":
                    branch = result.get("branch")
                    next_edges = [e for e in next_edges if (e.get("sourceHandle") or "true") == branch]

                for e in next_edges:
                    target_id = str(e.get("target"))
                    if target_id not in visited:
                        queue.append(target_id)

        except Exception as exc:  # noqa: BLE001
            status = "error"
            error = str(exc)
            logs.append(f"[{_ts(_now())}] [ERROR] Unhandled exception: {exc}")

        stopped_at = _now()
        duration_ms = max(1, int((stopped_at - started_at).total_seconds() * 1000))
        timeline.append("Completed" if status == "success" else status.replace("_", " ").title())
        logs.append(f"[{_ts(stopped_at)}] Workflow finished with status: {status}.")

        return ExecutionResult(
            status=status,
            started_at=started_at,
            stopped_at=stopped_at,
            duration_ms=duration_ms,
            timeline=timeline,
            logs=logs,
            node_outputs=context,
            input=first_input,
            output={"status": status, "nodes_executed": len(visited), "results": context, "error": error},
            error=error,
        )

    @staticmethod
    def _node_params(node: dict[str, Any]) -> dict[str, Any]:
        # Delegate to `param_adapter.normalize` so every handler receives
        # `{provider, action, payload}` (or the appropriate shape for its
        # node type) — regardless of whether the canvas wrote the friendly
        # fields (`gmailAccount`, `slackChannel`, etc.) or a structured
        # `data.parameters` block.
        return normalize(node)


async def run_workflow(workflow: "Workflow", org_id: str, db: AsyncSession, dry_run: bool = False) -> ExecutionResult:
    engine = NipunaWorkflowEngine()
    return await engine.run(workflow.nodes or [], workflow.edges or [], org_id, db, dry_run=dry_run)


async def resume_from_approval(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    org_id: str,
    db: AsyncSession,
    *,
    approval_node_id: str,
    approval_title: str,
    decision: str,
    approver_note: str | None,
    prior_context: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> ExecutionResult:
    """Continue a paused workflow from an approval node's outgoing edge.

    Walks the graph forward from `approval_node_id`, with the approval
    decision pre-injected into the engine context under the approval
    node's title. Treats the approval node itself as already-completed
    (it is not re-run). Returns a fresh `ExecutionResult` covering only
    the resumed portion — caller is responsible for persisting it.
    """
    started_at = _now()
    timeline: list[str] = ["Workflow Resumed"]
    logs: list[str] = [
        f"[{_ts(started_at)}] Workflow resumed after approval decision '{decision}'."
    ]
    context: dict[str, Any] = dict(prior_context or {})
    # Inject the decision so downstream nodes that template
    # `{{ <title>.decision }}` resolve correctly.
    context[approval_title] = {
        "status": decision,
        "decision": decision,
        "note": approver_note,
    }

    by_id = {str(n["id"]): n for n in nodes}
    outgoing: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        outgoing.setdefault(str(e["source"]), []).append(e)

    status = "success"
    error: str | None = None
    # The approval node itself is treated as already-completed (the decision
    # is already injected into `context[approval_title]`). Start the walk from
    # its outgoing neighbors so we don't re-run it and immediately re-pause.
    visited: set[str] = {str(approval_node_id)}
    timeline.append(f"{approval_title} ({decision})")
    logs.append(f"[{_ts(_now())}] Approval decision '{decision}' recorded for '{approval_title}'.")
    queue: list[str] = [str(t) for e in outgoing.get(str(approval_node_id), []) for t in [e.get("target")] if t]

    try:
        while queue:
            node_id = queue.pop(0)
            if node_id in visited or node_id not in by_id:
                continue
            visited.add(node_id)
            node = by_id[node_id]
            title = str(node.get("data", {}).get("title") or node_id)
            node_type = str(node.get("data", {}).get("type", "unknown"))

            params = resolve(normalize(node), context)
            handler = get_handler(node_type)

            logs.append(f"[{_ts(_now())}] Running '{title}' ({node_type})...")
            result = await handler(node, params, org_id, db, dry_run=dry_run)
            context[title] = result
            timeline.append(title)

            if result.get("status") == "error":
                status = "error"
                error = str(result.get("error") or result.get("reason") or "Node failed")
                logs.append(f"[{_ts(_now())}] [ERROR] '{title}': {error}")
                break

            if result.get("status") == "waiting_approval":
                status = "waiting_approval"
                logs.append(f"[{_ts(_now())}] '{title}' is waiting for human approval — pausing here.")
                break

            logs.append(f"[{_ts(_now())}] '{title}' completed.")

            next_edges = outgoing.get(node_id, [])
            if node_type == "if":
                branch = result.get("branch")
                next_edges = [e for e in next_edges if (e.get("sourceHandle") or "true") == branch]

            for e in next_edges:
                target_id = str(e.get("target"))
                if target_id not in visited:
                    queue.append(target_id)
    except Exception as exc:  # noqa: BLE001
        status = "error"
        error = str(exc)
        logs.append(f"[{_ts(_now())}] [ERROR] Unhandled exception during resume: {exc}")

    stopped_at = _now()
    duration_ms = max(1, int((stopped_at - started_at).total_seconds() * 1000))
    timeline.append("Completed" if status == "success" else status.replace("_", " ").title())
    logs.append(f"[{_ts(stopped_at)}] Resumed workflow finished with status: {status}.")

    return ExecutionResult(
        status=status,
        started_at=started_at,
        stopped_at=stopped_at,
        duration_ms=duration_ms,
        timeline=timeline,
        logs=logs,
        node_outputs=context,
        input=dict(prior_context or {}),
        output={
            "status": status,
            "resumed": True,
            "approval_decision": decision,
            "approver_note": approver_note,
            "nodes_executed": len(visited),
            "results": context,
            "error": error,
        },
        error=error,
    )
