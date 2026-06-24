from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


from datetime import datetime

class MemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str | None = None
    last_name: str | None = None
    email: str
    role: str
    status: str
    created_at: datetime


class TeamResponse(BaseModel):
    seats_used: int
    max_seats: int
    admin_count: int
    pending_reviews: int
    members: list[MemberResponse]


class InviteRequest(BaseModel):
    email: str = Field(..., max_length=320)
    role: str = Field(..., pattern=r"^(admin|member|viewer)$")
