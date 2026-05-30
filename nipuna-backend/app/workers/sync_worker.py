import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.models.integration import Integration
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

settings = get_settings()
sync_engine = create_engine(settings.sync_database_url)
SyncSessionLocal = sessionmaker(bind=sync_engine)


@celery_app.task(name="app.workers.sync_worker.sync_all_integrations")
def sync_all_integrations() -> dict[str, int]:
    session = SyncSessionLocal()
    processed = 0

    try:
        integrations = session.execute(
            select(Integration).where(Integration.status == "connected")
        ).scalars().all()

        now = datetime.now(timezone.utc)

        for integration in integrations:
            try:
                processed += 1
                if integration.last_synced:
                    delta = (now - integration.last_synced).total_seconds()
                    if delta < 900:
                        integration.sync_health = 100
                    elif delta < 1800:
                        integration.sync_health = 90
                    elif delta < 3600:
                        integration.sync_health = 70
                    elif delta < 86400:
                        integration.sync_health = 50
                    else:
                        integration.sync_health = 0
                else:
                    integration.sync_health = 0

                if integration.composio_connection_id:
                    _verify_composio_connection(integration)

            except Exception as exc:
                logger.exception("Error syncing integration %s: %s", integration.id, exc)
                continue

        session.commit()
    finally:
        session.close()

    return {"integrations_processed": processed}


def _verify_composio_connection(integration: Integration) -> None:
    try:
        from composio import ComposioClient
        client = ComposioClient(api_key=settings.composio_api_key)
        connections = client.get_connections(entity_id=str(integration.org_id))
        active = any(
            c.get("id") == integration.composio_connection_id and c.get("status") == "connected"
            for c in connections
        )
        if not active:
            integration.status = "error"
    except Exception as exc:
        logger.warning("Composio verification failed for %s: %s", integration.id, exc)
