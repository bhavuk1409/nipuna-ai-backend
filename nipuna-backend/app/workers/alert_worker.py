import logging

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models.alert import Alert
from app.models.organization import Organization
from app.models.user import User
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

settings = get_settings()
sync_engine = create_engine(settings.sync_database_url)
SyncSessionLocal = sessionmaker(bind=sync_engine)


def _get_redis():
    import redis as redis_lib
    try:
        return redis_lib.from_url(settings.redis_url)
    except Exception:
        return None


@celery_app.task(name="app.workers.alert_worker.run_all_alert_checks")
def run_all_alert_checks() -> dict[str, int]:
    session = SyncSessionLocal()
    r = _get_redis()
    orgs_checked = 0
    alerts_created = 0

    try:
        orgs = session.execute(select(Organization)).scalars().all()

        for org in orgs:
            orgs_checked += 1
            try:
                alerts_created += _check_credit_low(session, org, r)
                alerts_created += _check_agent_idle(session, org, r)
                alerts_created += _check_integration_error(session, org, r)
                alerts_created += _check_seat_limit(session, org, r)
                alerts_created += _check_subscription_expiry(session, org, r)
            except Exception as exc:
                logger.exception("Error checking org %s: %s", org.id, exc)
                continue
    finally:
        session.close()
        if r:
            r.close()

    return {"organizations_checked": orgs_checked, "alerts_created": alerts_created}


def _should_fire(org_id: str, rule_id: str, r) -> bool:
    if r is None:
        return True
    try:
        key = f"alert_dedup:{org_id}:{rule_id}"
        if r.exists(key):
            return False
        r.setex(key, 86400, "1")
        return True
    except Exception:
        return True


def _check_credit_low(session: Session, org: Organization, r) -> int:
    if org.ai_credits >= 10:
        return 0
    if not _should_fire(str(org.id), "CREDIT_LOW", r):
        return 0

    alert = Alert(org_id=org.id, rule_id="CREDIT_LOW", severity="warning",
                  message=f"AI credits low: {org.ai_credits} remaining")
    session.add(alert)
    session.commit()

    admin = session.execute(
        select(User).where(User.org_id == org.id, User.role == "admin")
    ).scalar_one_or_none()
    if admin:
        import asyncio
        from app.services.notifications.email import send_email
        asyncio.create_task(
            send_email(admin.email, "Low AI Credits",
                       f"<p>Your AI credits are running low ({org.ai_credits} remaining).</p>")
        )
    return 1


def _check_agent_idle(session: Session, org: Organization, r) -> int:
    from datetime import datetime, timedelta, timezone
    from app.models.agent import Agent
    from app.models.conversation import Message

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    idle_agents = session.execute(
        select(Agent).where(
            Agent.org_id == org.id,
            Agent.status == "active",
        )
    ).scalars().all()

    active_ids = [a.id for a in idle_agents]
    if not active_ids:
        return 0

    recent_msg_conv_ids = session.execute(
        select(Message.conversation_id)
        .where(Message.created_at >= cutoff)
    ).scalars().all()

    count = 0
    for agent in idle_agents:
        if not _should_fire(str(org.id), f"AGENT_IDLE:{agent.id}", r):
            continue
        alert = Alert(org_id=org.id, rule_id="AGENT_IDLE", severity="info",
                      message=f"Agent '{agent.name}' has been idle for over 24 hours")
        session.add(alert)
        count += 1

    if count:
        session.commit()
    return count


def _check_integration_error(session: Session, org: Organization, r) -> int:
    from app.models.integration import Integration

    bad_integrations = session.execute(
        select(Integration).where(
            Integration.org_id == org.id,
            Integration.sync_health < 80,
        )
    ).scalars().all()

    count = 0
    for integration in bad_integrations:
        if not _should_fire(str(org.id), "INTEGRATION_ERROR", r):
            continue
        alert = Alert(org_id=org.id, rule_id="INTEGRATION_ERROR", severity="warning",
                      message=f"Integration '{integration.display_name}' has sync health {integration.sync_health}")
        session.add(alert)
        count += 1

    if count:
        session.commit()
    return count


def _check_seat_limit(session: Session, org: Organization, r) -> int:
    from sqlalchemy import func

    seats_used = session.execute(
        select(func.count(User.id)).where(
            User.org_id == org.id,
            User.status != "suspended",
        )
    ).scalar() or 0

    if seats_used < org.seats_max:
        return 0
    if not _should_fire(str(org.id), "SEAT_LIMIT", r):
        return 0

    alert = Alert(org_id=org.id, rule_id="SEAT_LIMIT", severity="warning",
                  message=f"Seat limit reached: {seats_used}/{org.seats_max}")
    session.add(alert)
    session.commit()
    return 1


def _check_subscription_expiry(session: Session, org: Organization, r) -> int:
    from app.models.billing import BillingEvent
    from datetime import datetime, timedelta, timezone

    latest = session.execute(
        select(BillingEvent)
        .where(BillingEvent.org_id == org.id, BillingEvent.status == "paid")
        .order_by(BillingEvent.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not latest:
        return 0

    expires = latest.created_at + timedelta(days=30)
    if expires > datetime.now(timezone.utc) + timedelta(days=7):
        return 0

    if not _should_fire(str(org.id), "SUBSCRIPTION_EXPIRY", r):
        return 0

    alert = Alert(org_id=org.id, rule_id="SUBSCRIPTION_EXPIRY", severity="critical",
                  message=f"Subscription expires on {expires.date()}")
    session.add(alert)
    session.commit()

    admin = session.execute(
        select(User).where(User.org_id == org.id, User.role == "admin")
    ).scalar_one_or_none()
    if admin:
        import asyncio
        from app.services.notifications.email import send_email
        from app.services.notifications.whatsapp import send_whatsapp
        asyncio.create_task(
            send_email(admin.email, "Subscription Expiring",
                       f"<p>Your subscription expires on {expires.date()}.</p>")
        )
        if admin.phone:
            asyncio.create_task(
                send_whatsapp(admin.phone, f"Your Nipuna AI subscription expires on {expires.date()}.")
            )
    return 1
