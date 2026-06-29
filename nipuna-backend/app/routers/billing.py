from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.billing import BillingEvent
from app.models.organization import Organization
from app.models.user import User
from app.schemas.billing import (
    BillingEventResponse,
    BillingStatusResponse,
    CancelResponse,
    SubscribeRequest,
    SubscribeResponse,
)

router = APIRouter(prefix="/billing", tags=["billing"])

PLAN_AMOUNTS = {
    "free": "Rs 0/mo",
    "starter": "Rs 4999/mo",
    "growth": "Rs 9999/mo",
    "enterprise": "Rs 19999/mo",
}

PLAN_CONFIG = {
    "starter": "RAZORPAY_PLAN_STARTER",
    "growth": "RAZORPAY_PLAN_GROWTH",
    "enterprise": "RAZORPAY_PLAN_ENTERPRISE",
}


@router.get("/status", response_model=BillingStatusResponse)
async def get_billing_status(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BillingStatusResponse:
    recent_result = await db.execute(
        select(BillingEvent)
        .where(BillingEvent.org_id == org.id)
        .order_by(BillingEvent.created_at.desc())
        .limit(10)
    )
    recent_events = recent_result.scalars().all()

    next_invoice = ""
    if recent_events:
        paid = [e for e in recent_events if e.status == "paid"]
        if paid:
            next_invoice = paid[0].created_at.isoformat() if paid[0].created_at else ""

    return BillingStatusResponse(
        current_plan=org.plan,
        amount_display=PLAN_AMOUNTS.get(org.plan, "Rs 0/mo"),
        next_invoice_date=next_invoice,
        recent_activity=[BillingEventResponse.model_validate(e) for e in recent_events],
    )


@router.post("/subscribe", response_model=SubscribeResponse)
async def subscribe(
    body: SubscribeRequest,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscribeResponse:
    settings = get_settings()
    plan_config_key = PLAN_CONFIG.get(body.plan_name)
    if not plan_config_key:
        raise HTTPException(status_code=400, detail="Invalid plan")

    plan_id = getattr(settings, plan_config_key.lower(), None)
    if not plan_id:
        raise HTTPException(status_code=400, detail="Plan not configured")

    import razorpay

    client = razorpay.Client(
        auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
    )

    try:
        subscription = client.subscription.create(
            {"plan_id": plan_id, "total_count": 12, "quantity": 1}
        )
    except Exception as exc:
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        raise HTTPException(status_code=500, detail="Failed to create subscription")

    return SubscribeResponse(short_url=subscription["short_url"])


@router.post("/cancel", response_model=CancelResponse)
async def cancel_subscription(
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CancelResponse:
    settings = get_settings()

    latest_sub_result = await db.execute(
        select(BillingEvent)
        .where(
            BillingEvent.org_id == org.id,
            BillingEvent.razorpay_subscription_id.isnot(None),
        )
        .order_by(BillingEvent.created_at.desc())
        .limit(1)
    )
    latest = latest_sub_result.scalar_one_or_none()

    if latest and latest.razorpay_subscription_id:
        import razorpay

        client = razorpay.Client(
            auth=(settings.razorpay_key_id, settings.razorpay_key_secret)
        )
        try:
            client.subscription.cancel(latest.razorpay_subscription_id)
        except Exception as exc:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)

    org.plan = "free"
    db.add(org)

    event = BillingEvent(
        org_id=org.id,
        event_type="cancelled",
        status="cancelled",
    )
    db.add(event)
    await db.commit()

    return CancelResponse(status="cancelled")
