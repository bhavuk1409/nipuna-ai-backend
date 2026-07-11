"""Extra node handlers for the Nipuna workflow engine.

Handlers that are out of scope for the initial engine release live here.
They are NOT auto-registered with `app.services.workflow_engine.handlers.HANDLERS`
yet — the user/main agent needs to add a one-line entry per handler, e.g.:

    from app.services.workflow_engine.extra_handlers import handle_schedule_node
    HANDLERS["schedule"] = handle_schedule_node
    HANDLERS["cron"] = handle_schedule_node

Adding new node types here keeps `handlers.py` stable for the agent that owns it.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def handle_schedule_node(
    node: dict[str, Any],
    params: dict[str, Any],
    org_id: str,
    db: AsyncSession,
    *,
    dry_run: bool = False,  # noqa: ARG001
) -> dict[str, Any]:
    """Handler for `schedule` and `cron` trigger nodes.

    Computes the next firing time of the configured cron expression and
    returns it to downstream nodes (so the rest of the workflow can use
    `{{ Schedule.next_run }}` in its parameters). The actual "fire at that
    time" logic is owned by `app.services.workflow_engine.scheduler.tick`,
    which is called from Celery beat every 60s.

    Parameters (from `node["data"]["parameters"]`):
        cron:     Cron expression, e.g. "0 9 * * *". Required.
        timezone: IANA timezone name, e.g. "Asia/Kolkata". Optional, default "UTC".
    """
    cron = params.get("cron")
    if not cron or not isinstance(cron, str):
        return {"status": "error", "error": "Invalid cron expression"}

    tz_name = str(params.get("timezone") or "UTC")
    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("Unknown timezone '%s' on schedule node — falling back to UTC", tz_name)
        tz = ZoneInfo("UTC")
        tz_name = "UTC"

    try:
        now = datetime.now(tz)
        itr = croniter(cron, now)
        next_run = itr.get_next(datetime)
    except Exception as exc:  # noqa: BLE001 — croniter raises a few different types
        logger.warning("Invalid cron expression '%s': %s", cron, exc)
        return {"status": "error", "error": "Invalid cron expression"}

    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=tz)

    return {
        "status": "success",
        "cron": cron,
        "next_run": next_run.isoformat(),
        "timezone": tz_name,
    }
