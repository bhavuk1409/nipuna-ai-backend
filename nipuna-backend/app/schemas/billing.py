from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SubscribeRequest(BaseModel):
    plan_name: str = Field(..., pattern=r"^(starter|growth|enterprise)$")


class SubscribeResponse(BaseModel):
    short_url: str


class CancelResponse(BaseModel):
    status: str = "cancelled"


class BillingEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    event_type: str
    amount: Decimal | None = None
    currency: str
    status: str
    created_at: datetime


class BillingStatusResponse(BaseModel):
    current_plan: str
    amount_display: str
    next_invoice_date: str
    recent_activity: list[BillingEventResponse]
