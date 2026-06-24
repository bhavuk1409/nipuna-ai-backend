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
        email_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Low AI Credits — Nipuna AI</title>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      
      .wrapper {{
        width: 100%;
        background-color: #f8fafc;
        padding: 40px 20px;
      }}
      
      .container {{
        max-width: 580px;
        margin: 0 auto;
        background-color: #ffffff;
        border: 1px solid #eef0f2;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
        overflow: hidden;
      }}
      
      .content-padding {{
        padding: 40px 40px 32px 40px;
      }}
      
      .header {{
        padding-bottom: 24px;
        border-bottom: 1px solid #f1f3f5;
        margin-bottom: 32px;
      }}
      
      .header-logo {{
        vertical-align: middle;
        margin-right: 10px;
        width: 24px;
        height: 24px;
      }}
      
      .header-text {{
        font-size: 15px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .alert-card {{
        background-color: #fffbeb;
        border: 1px solid #fef3c7;
        border-radius: 12px;
        padding: 20px;
        margin-top: 24px;
        margin-bottom: 24px;
      }}
      
      .alert-title {{
        font-size: 16px;
        font-weight: 600;
        color: #b45309;
        margin: 0 0 8px 0;
      }}
      
      .alert-desc {{
        font-size: 14px;
        line-height: 1.6;
        color: #d97706;
        margin: 0;
      }}
      
      .footer {{
        padding: 24px 40px;
        background-color: #ffffff;
        border-top: 1px solid #f1f3f5;
      }}
      
      .footer-col-left {{
        float: left;
        width: 50%;
      }}
      
      .footer-col-right {{
        float: right;
        width: 50%;
        text-align: right;
      }}
      
      .footer-logo {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
        margin-right: 8px;
        opacity: 0.8;
      }}
      
      .footer-brand {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .footer-sub {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        font-weight: 400;
      }}
      
      .footer-copy {{
        font-size: 12px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }}
      
      .clearfix::after {{
        content: "";
        clear: both;
        display: table;
      }}
      
      @media screen and (max-width: 600px) {{
        .wrapper {{
          padding: 20px 12px;
        }}
        
        .content-padding {{
          padding: 24px 20px 24px 20px;
        }}
        
        .footer {{
          padding: 20px;
        }}
        
        .footer-col-left, .footer-col-right {{
          float: none;
          width: 100%;
          text-align: left;
        }}
        
        .footer-col-right {{
          margin-top: 16px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="container">
        
        <div class="content-padding">
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Attention Required
          </h1>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            Hello,<br><br>
            We are writing to inform you that your workspace AI credits are running low. Please top up your credits to avoid any interruption in agent operations.
          </p>
          
          <div class="alert-card">
            <h3 class="alert-title">Low AI Credits Warning</h3>
            <p class="alert-desc">Remaining Credits: <strong>{org.ai_credits}</strong></p>
          </div>
          
          <!-- Action Button -->
          <div style="margin-top: 32px; margin-bottom: 24px; text-align: center;">
            <a href="{settings.frontend_url}/settings/billing" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif;">
              Manage Billing &nbsp; <span style="font-size: 14px; font-weight: 400; vertical-align: middle;">➔</span>
            </a>
          </div>
        </div>
        
        <div class="footer clearfix">
          <div class="footer-col-left">
            <div>
              <img class="footer-logo" src="https://www.nipunaai.in/logo.png" alt="" />
              <span class="footer-brand">Nipuna AI</span>
            </div>
            <div class="footer-sub">AI Operating System for Business</div>
          </div>
          <div class="footer-col-right">
            <p class="footer-copy">© 2026 Nipuna AI.<br>All rights reserved.</p>
          </div>
        </div>
        
      </div>
    </div>
  </body>
</html>
"""
        asyncio.create_task(
            send_email(admin.email, "Low AI Credits — Nipuna AI", email_html)
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
        
        email_html = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Subscription Expiring — Nipuna AI</title>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
      
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }}
      
      .wrapper {{
        width: 100%;
        background-color: #f8fafc;
        padding: 40px 20px;
      }}
      
      .container {{
        max-width: 580px;
        margin: 0 auto;
        background-color: #ffffff;
        border: 1px solid #eef0f2;
        border-radius: 16px;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.02);
        overflow: hidden;
      }}
      
      .content-padding {{
        padding: 40px 40px 32px 40px;
      }}
      
      .header {{
        padding-bottom: 24px;
        border-bottom: 1px solid #f1f3f5;
        margin-bottom: 32px;
      }}
      
      .header-logo {{
        vertical-align: middle;
        margin-right: 10px;
        width: 24px;
        height: 24px;
      }}
      
      .header-text {{
        font-size: 15px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .alert-card {{
        background-color: #fef2f2;
        border: 1px solid #fee2e2;
        border-radius: 12px;
        padding: 20px;
        margin-top: 24px;
        margin-bottom: 24px;
      }}
      
      .alert-title {{
        font-size: 16px;
        font-weight: 600;
        color: #991b1b;
        margin: 0 0 8px 0;
      }}
      
      .alert-desc {{
        font-size: 14px;
        line-height: 1.6;
        color: #b91c1c;
        margin: 0;
      }}
      
      .footer {{
        padding: 24px 40px;
        background-color: #ffffff;
        border-top: 1px solid #f1f3f5;
      }}
      
      .footer-col-left {{
        float: left;
        width: 50%;
      }}
      
      .footer-col-right {{
        float: right;
        width: 50%;
        text-align: right;
      }}
      
      .footer-logo {{
        width: 20px;
        height: 20px;
        vertical-align: middle;
        margin-right: 8px;
        opacity: 0.8;
      }}
      
      .footer-brand {{
        font-size: 13px;
        font-weight: 600;
        color: #0f172a;
        vertical-align: middle;
      }}
      
      .footer-sub {{
        font-size: 11px;
        color: #64748b;
        margin-top: 4px;
        font-weight: 400;
      }}
      
      .footer-copy {{
        font-size: 12px;
        color: #64748b;
        margin: 0;
        line-height: 1.6;
      }}
      
      .clearfix::after {{
        content: "";
        clear: both;
        display: table;
      }}
      
      @media screen and (max-width: 600px) {{
        .wrapper {{
          padding: 20px 12px;
        }}
        
        .content-padding {{
          padding: 24px 20px 24px 20px;
        }}
        
        .footer {{
          padding: 20px;
        }}
        
        .footer-col-left, .footer-col-right {{
          float: none;
          width: 100%;
          text-align: left;
        }}
        
        .footer-col-right {{
          margin-top: 16px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="wrapper">
      <div class="container">
        
        <div class="content-padding">
          <div class="header">
            <img class="header-logo" src="https://www.nipunaai.in/logo.png" alt="Nipuna AI" />
            <span class="header-text">Nipuna AI</span>
          </div>
          
          <h1 style="font-size: 32px; font-weight: 700; color: #0f172a; margin: 0 0 12px 0; letter-spacing: -0.025em; line-height: 1.15;">
            Action Required
          </h1>
          <p style="font-size: 14px; line-height: 1.6; color: #475569; margin: 0 0 24px 0; font-weight: 400;">
            Hello,<br><br>
            Your workspace subscription is expiring soon. Please renew your subscription to maintain active access to all AI agents and automation flows.
          </p>
          
          <div class="alert-card">
            <h3 class="alert-title">Subscription Expiring</h3>
            <p class="alert-desc">Expiry Date: <strong>{expires.date()}</strong></p>
          </div>
          
          <!-- Action Button -->
          <div style="margin-top: 32px; margin-bottom: 24px; text-align: center;">
            <a href="{settings.frontend_url}/settings/billing" style="display: inline-block; background-color: #0f172a; color: #ffffff; text-decoration: none; padding: 12px 24px; font-size: 13px; font-weight: 600; border-radius: 6px; font-family: 'Inter', sans-serif;">
              Renew Subscription &nbsp; <span style="font-size: 14px; font-weight: 400; vertical-align: middle;">➔</span>
            </a>
          </div>
        </div>
        
        <div class="footer clearfix">
          <div class="footer-col-left">
            <div>
              <img class="footer-logo" src="https://www.nipunaai.in/logo.png" alt="" />
              <span class="footer-brand">Nipuna AI</span>
            </div>
            <div class="footer-sub">AI Operating System for Business</div>
          </div>
          <div class="footer-col-right">
            <p class="footer-copy">© 2026 Nipuna AI.<br>All rights reserved.</p>
          </div>
        </div>
        
      </div>
    </div>
  </body>
</html>
"""
        asyncio.create_task(
            send_email(admin.email, "Subscription Expiring — Nipuna AI", email_html)
        )
        if admin.phone:
            asyncio.create_task(
                send_whatsapp(admin.phone, f"Your Nipuna AI subscription expires on {expires.date()}.")
            )
    return 1
