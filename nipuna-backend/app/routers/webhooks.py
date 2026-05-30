import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models.billing import BillingEvent
from app.models.organization import Organization

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay", include_in_schema=False)
async def razorpay_webhook(
    request: Request,
) -> dict[str, str]:
    settings = get_settings()
    webhook_secret = settings.razorpay_webhook_secret
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not configured")
        return {"status": "ignored"}

    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    expected_sig = hmac.new(
        webhook_secret.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Invalid Razorpay webhook signature")
        return {"status": "ignored"}

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError:
        return {"status": "ignored"}

    event = payload.get("event", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    subscription = payload.get("payload", {}).get("subscription", {}).get("entity", {})

    subscription_id = subscription.get("id") or payment.get("subscription_id", "")

    import sentry_sdk
    from app.database import SyncSessionLocal

    session = SyncSessionLocal()
    try:
        if event == "payment.captured":
            result = session.execute(
                select(Organization).where(
                    Organization.id.isnot(None)
                )
            )

            amount = payment.get("amount", 0) / 100.0
            currency = payment.get("currency", "INR")
            payment_id = payment.get("id", "")

            org_result = session.execute(
                select(Organization).where(
                    Organization.id.isnot(None)
                )
            )
            orgs = org_result.scalars().all()

            for org in orgs:
                event_record = BillingEvent(
                    org_id=org.id,
                    event_type="payment.captured",
                    razorpay_subscription_id=subscription_id,
                    razorpay_payment_id=payment_id,
                    amount=amount,
                    currency=currency,
                    status="paid",
                )
                session.add(event_record)

            for org in orgs:
                org.plan = org.plan

            session.commit()
            logger.info("Processed payment.captured event: %s", payment_id)

        elif event == "subscription.cancelled":
            org_result = session.execute(
                select(Organization).where(
                    Organization.id.isnot(None)
                )
            )
            orgs = org_result.scalars().all()
            for org in orgs:
                event_record = BillingEvent(
                    org_id=org.id,
                    event_type="subscription.cancelled",
                    razorpay_subscription_id=subscription_id,
                    status="cancelled",
                )
                session.add(event_record)
            session.commit()
            logger.info("Processed subscription.cancelled event: %s", subscription_id)

    except Exception as exc:
        session.rollback()
        sentry_sdk.capture_exception(exc)
        logger.exception("Error processing Razorpay webhook: %s", exc)
    finally:
        session.close()

    return {"status": "ok"}
