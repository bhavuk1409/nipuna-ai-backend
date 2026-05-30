from pydantic import BaseModel, Field


class OnboardingRequest(BaseModel):
    company_name: str = Field(..., max_length=255)
    industry: str = Field(..., max_length=255)
    team_size: str = Field(..., max_length=64)


class OnboardingResponse(BaseModel):
    status: str = "ok"
    org_id: str
