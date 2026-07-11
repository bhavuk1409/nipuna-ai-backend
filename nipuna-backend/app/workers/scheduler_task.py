"""Celery task that drives the workflow scheduler.

Run this from celery beat every 60 seconds. It opens a fresh async DB
session, calls `scheduler.tick(db)`, and logs how many workflows were run.

# To enable, add to your celery beat_schedule in app/workers/celery_app.py:
#
#     beat_schedule={
#         ...existing entries...,
#         "tick-workflow-scheduler": {
#             "task": "app.workers.scheduler_task.tick_scheduled_workflows",
#             "schedule": 60.0,  # every 60 seconds
#         },
#     }
#
# And add "app.workers.scheduler_task" to the Celery `include=[...]` list so
# the worker discovers this task at boot.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.database import AsyncSessionLocal
from app.services.workflow_engine.scheduler import tick
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.scheduler_task.tick_scheduled_workflows")
def tick_scheduled_workflows() -> dict[str, Any]:
    """Celery entrypoint: open an async DB session, run one scheduler tick."""
    return asyncio.run(_run_tick())


async def _run_tick() -> dict[str, Any]:
    async with AsyncSessionLocal() as db:
        result = await tick(db)
        logger.info(
            "Workflow scheduler tick: count=%s ran=%s",
            result.get("count"),
            result.get("ran"),
        )
        return result
