"""Nipuna Workflow Engine.

A purpose-built, dependency-free workflow execution engine — replaces the
n8n integration entirely. It executes the exact node/edge graph produced by
the Nipuna canvas (React Flow format used in `dashboard/workflows.tsx`),
dispatching each node to a real backend action via the existing MCP/Composio
gateway (`app.services.mcp.gateway.execute_tool`).

Public entrypoint: `run_workflow(workflow, org_id, db)` in `engine.py`.
"""

from app.services.workflow_engine.engine import (
    NipunaWorkflowEngine,
    resume_from_approval,
    run_workflow,
)

__all__ = ["NipunaWorkflowEngine", "resume_from_approval", "run_workflow"]
