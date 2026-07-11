"""Workflow scheduler — finds workflows with `schedule`/`cron` trigger nodes
that are due to run and kicks them off via the Nipuna workflow engine.

Designed to be called by a Celery beat task every 60 seconds
(`app.workers.scheduler_task.tick_scheduled_workflows`). The `tick()` function
is idempotent in the face of a beat that runs more often than the cron period:
a workflow is only re-run if its `last_run_at` is older than the cron's most
recent scheduled fire (minus a small buffer for beat-timing skew).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workflow import Workflow
from app.services.workflow_engine.engine import run_workflow

logger = logging.getLogger(__name__)

# Generous buffer so a beat that fires a few seconds early/late doesn't
# accidentally double-run a workflow.
SCHEDULE_SKEW_BUFFER = timedelta(seconds=60)

# Node `data.type` values that mean "this workflow has a schedule trigger".
SCHEDULE_NODE_TYPES = frozenset({"schedule", "cron"})


def _iter_cron_candidates(
    workflow: Workflow,
) -> list[tuple[dict[str, Any], str, ZoneInfo]]:
    """Yield (node, cron, tz) for every schedule/cron trigger in this workflow."""
    out: list[tuple[dict[str, Any], str, ZoneInfo]] = []
    for node in workflow.nodes or []:
        data = node.get("data") or {}
        if str(data.get("type", "")).lower() not in SCHEDULE_NODE_TYPES:
            continue
        params = data.get("parameters") or {}
        cron = params.get("cron")
        if not cron or not isinstance(cron, str):
            continue
        tz_name = str(params.get("timezone") or "UTC")
        try:
            tz = ZoneInfo(tz_name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(
                "Workflow %s: unknown timezone '%s' on schedule node — using UTC",
                workflow.id, tz_name,
            )
            tz = ZoneInfo("UTC")
        out.append((node, cron, tz))
    return out


def _is_due(workflow: Workflow, now: datetime) -> bool:
    """A workflow is "due" if any of its schedule triggers has a fire time
    that has passed since the last run (or has never been run)."""
    for _node, cron, tz in _iter_cron_candidates(workflow):
        try:
            # Anchor croniter at the last run (or 1 period before `now` if never run)
            # so we can ask "was the most recent fire time in the past?".
            anchor = workflow.last_run_at or (now.astimezone(tz) - timedelta(days=2))
            if anchor.tzinfo is None:
                anchor = anchor.replace(tzinfo=tz)
            else:
                anchor = anchor.astimezone(tz)
            itr = croniter(cron, anchor)
            next_fire = itr.get_next(datetime)
            if next_fire.tzinfo is None:
                next_fire = next_fire.replace(tzinfo=tz)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Workflow %s: skipping bad cron '%s': %s", workflow.id, cron, exc)
            continue

        # If the next fire is within the beat window (now +/- buffer), it's due.
        if next_fire <= now.astimezone(tz) + SCHEDULE_SKEW_BUFFER:
            return True
    return False


async def find_due_scheduled_workflows(db: AsyncSession) -> list[Workflow]:
    """Return all active workflows that are currently due to run.

    Implementation note: we don't use a JSONB containment query because the
    `nodes` structure can store the `type` either on `data.type` or on the
    top-level React Flow `type` field, and we want to be lenient. Loading
    active workflows and filtering in Python is fine at the current scale
    (one tenant = tens of workflows at most).
    """
    result = await db.execute(
        select(Workflow).where(Workflow.status == "active")
    )
    candidates = result.scalars().all()
    now = datetime.now(timezone.utc)
    return [wf for wf in candidates if _is_due(wf, now)]


async def tick(db: AsyncSession) -> dict[str, Any]:
    """One scheduler heartbeat: find due workflows, run them, persist last_run_at.

    Returns a small summary dict suitable for logging / Celery result inspection.
    """
    now = datetime.now(timezone.utc)
    ran: list[str] = []

    try:
        due = await find_due_scheduled_workflows(db)
    except Exception as exc:  # noqa: BLE001
        logger.exception("find_due_scheduled_workflows failed: %s", exc)
        await db.rollback()
        return {"ticked_at": now.isoformat(), "ran": [], "count": 0, "error": str(exc)}

    for workflow in due:
        try:
            await run_workflow(workflow, str(workflow.org_id), db)
            workflow.last_run_at = now
            ran.append(str(workflow.id))
            logger.info(
                "Scheduler ran workflow %s (%s) — cron: %s",
                workflow.id, workflow.name,
                [cron for _node, cron, _tz in _iter_cron_candidates(workflow)],
            )
            # Commit per workflow so a single failure doesn't lose the others.
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Scheduled run of workflow %s failed: %s", workflow.id, exc)
            await db.rollback()

    return {"ticked_at": now.isoformat(), "ran": ran, "count": len(ran)}
