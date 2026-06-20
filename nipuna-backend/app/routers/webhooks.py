import hashlib
import hmac
import json
import logging
import uuid

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException, Request
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
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    settings = get_settings()
    webhook_secret = settings.razorpay_webhook_secret
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET is not configured")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    body_bytes = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    expected_sig = hmac.new(
        webhook_secret.encode(),
        body_bytes,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_sig, signature):
        logger.warning("Invalid Razorpay webhook signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    try:
        payload = json.loads(body_bytes)
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON payload: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
    subscription = payload.get("payload", {}).get("subscription", {}).get("entity", {})

    subscription_id = subscription.get("id") or payment.get("subscription_id", "")

    try:
        if event == "payment.captured":
            amount = payment.get("amount", 0) / 100.0
            currency = payment.get("currency", "INR")
            payment_id = payment.get("id", "")

            # Look up organization by notes first, then fallback to BillingEvent
            org_id = None
            notes = payment.get("notes", {}) or subscription.get("notes", {}) or {}
            org_id_str = notes.get("org_id") or notes.get("organization_id")
            clerk_org_id = notes.get("clerk_org_id")

            if org_id_str:
                try:
                    org_id = uuid.UUID(org_id_str)
                except ValueError:
                    pass

            if not org_id and clerk_org_id:
                org_res = await db.execute(
                    select(Organization.id).where(Organization.clerk_org_id == clerk_org_id)
                )
                org_id = org_res.scalar_one_or_none()

            if not org_id and subscription_id:
                stmt = select(BillingEvent.org_id).where(
                    BillingEvent.razorpay_subscription_id == subscription_id,
                    BillingEvent.org_id.isnot(None)
                ).limit(1)
                res = await db.execute(stmt)
                org_id = res.scalar_one_or_none()

            if not org_id:
                logger.warning("No matching organization found for Razorpay subscription_id=%s", subscription_id)

            event_record = BillingEvent(
                org_id=org_id,
                event_type="payment.captured",
                razorpay_subscription_id=subscription_id,
                razorpay_payment_id=payment_id,
                amount=amount,
                currency=currency,
                status="paid",
            )
            db.add(event_record)

            if org_id:
                org_res = await db.execute(select(Organization).where(Organization.id == org_id))
                org = org_res.scalar_one_or_none()
                if org:
                    # Update plan if specified in notes, otherwise keep as is
                    plan_name = notes.get("plan") or notes.get("plan_name")
                    if plan_name in ["free", "starter", "growth", "enterprise"]:
                        org.plan = plan_name
                    else:
                        org.plan = org.plan

            await db.commit()
            logger.info("Processed payment.captured event: %s for org: %s", payment_id, org_id)

        elif event == "subscription.cancelled":
            org_id = None
            notes = subscription.get("notes", {}) or payment.get("notes", {}) or {}
            org_id_str = notes.get("org_id") or notes.get("organization_id")
            clerk_org_id = notes.get("clerk_org_id")

            if org_id_str:
                try:
                    org_id = uuid.UUID(org_id_str)
                except ValueError:
                    pass

            if not org_id and clerk_org_id:
                org_res = await db.execute(
                    select(Organization.id).where(Organization.clerk_org_id == clerk_org_id)
                )
                org_id = org_res.scalar_one_or_none()

            if not org_id and subscription_id:
                stmt = select(BillingEvent.org_id).where(
                    BillingEvent.razorpay_subscription_id == subscription_id,
                    BillingEvent.org_id.isnot(None)
                ).limit(1)
                res = await db.execute(stmt)
                org_id = res.scalar_one_or_none()

            if not org_id:
                logger.warning("No matching organization found for Razorpay subscription_id=%s on cancellation", subscription_id)

            event_record = BillingEvent(
                org_id=org_id,
                event_type="subscription.cancelled",
                razorpay_subscription_id=subscription_id,
                status="cancelled",
            )
            db.add(event_record)

            if org_id:
                org_res = await db.execute(select(Organization).where(Organization.id == org_id))
                org = org_res.scalar_one_or_none()
                if org:
                    org.plan = "free"  # Downgrade on cancel

            await db.commit()
            logger.info("Processed subscription.cancelled event: %s for org: %s", subscription_id, org_id)

    except Exception as exc:
        await db.rollback()
        sentry_sdk.capture_exception(exc)
        logger.exception("Error processing Razorpay webhook: %s", exc)
        raise HTTPException(status_code=500, detail="Error processing webhook")

    return {"status": "ok"}
