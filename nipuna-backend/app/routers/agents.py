from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user, require_admin
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.services.ai.agent_templates import (
    AGENT_TEMPLATES,
    AgentTemplate,
    is_valid_template_id,
    list_templates,
)
from app.utils.audit import log_action

router = APIRouter(prefix="/agents", tags=["agents"])


# ──────────────────────────────────────────────────────────────────
# Schemas (template endpoints)
# ──────────────────────────────────────────────────────────────────


class AgentTemplateOut(BaseModel):
    id: str
    name: str
    domain: str
    objective: str
    icon: str
    color: str
    example_queries: list[str]
    default_tone: str
    default_currency: str
    preferred_datasources: list[str]


class AgentTemplateListResponse(BaseModel):
    templates: list[AgentTemplateOut]


class FromTemplateRequest(BaseModel):
    template_id: str
    name: str | None = None


def _template_to_out(t: AgentTemplate) -> AgentTemplateOut:
    return AgentTemplateOut(
        id=t.id,
        name=t.name,
        domain=t.domain,
        objective=t.objective,
        icon=t.icon,
        color=t.color,
        example_queries=list(t.example_queries),
        default_tone=t.default_tone,
        default_currency=t.default_currency,
        preferred_datasources=list(t.preferred_datasources),
    )


@router.get("", response_model=dict[str, list[AgentResponse]])
async def list_agents(
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, list[AgentResponse]]:
    result = await db.execute(
        select(Agent).where(
            Agent.org_id == org.id,
            Agent.status != "deleted",
        )
    )
    agents = result.scalars().all()
    return {"agents": [AgentResponse.model_validate(a) for a in agents]}


@router.post("", response_model=AgentResponse, status_code=201)
async def create_agent(
    body: AgentCreate,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    agent = Agent(
        org_id=org.id,
        name=body.name,
        domain=body.domain,
        objective=body.objective,
        status=body.status,
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()

    await log_action(db, org_id=org.id, user_id=user.id, action="agent_created",
                     metadata={"agent_id": str(agent.id), "name": agent.name})
    await db.commit()

    return AgentResponse.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.org_id == org.id,
            Agent.status != "deleted",
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return AgentResponse.model_validate(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    org: Organization = Depends(get_current_org),
    _user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.org_id == org.id,
            Agent.status != "deleted",
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.commit()
    return AgentResponse.model_validate(agent)


@router.delete("/{agent_id}", status_code=200)
async def delete_agent(
    agent_id: UUID,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    result = await db.execute(
        select(Agent).where(
            Agent.id == agent_id,
            Agent.org_id == org.id,
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.status = "deleted"
    await log_action(db, org_id=org.id, user_id=user.id, action="agent_deleted",
                     metadata={"agent_id": str(agent_id), "name": agent.name})
    await db.commit()
    return {"status": "deleted"}


# ──────────────────────────────────────────────────────────────────
# Template endpoints (PR4)
# ──────────────────────────────────────────────────────────────────


@router.get("/templates", response_model=AgentTemplateListResponse)
async def get_agent_templates(
    _user: User = Depends(get_current_user),
) -> AgentTemplateListResponse:
    """Public-ish: any active member of an org can see the template
    catalog. The FE uses this to render the empty-state cards and
    the "create from template" picker.
    """
    return AgentTemplateListResponse(
        templates=[_template_to_out(t) for t in list_templates()],
    )


@router.post("/from-template", response_model=AgentResponse, status_code=201)
async def create_agent_from_template(
    body: FromTemplateRequest,
    org: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AgentResponse:
    """Create a new ``Agent`` row for the active user from one of the
    registered templates. The template owns the voice / objective /
    icon / color; the org row records the ``template_id`` so the
    pipeline can recover the template on a later request.
    """
    if not is_valid_template_id(body.template_id):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown template_id. Valid: {sorted(AGENT_TEMPLATES.keys())}",
        )
    template = AGENT_TEMPLATES[body.template_id]
    agent = Agent(
        org_id=org.id,
        name=(body.name or template.name).strip()[:120] or template.name,
        domain=template.domain,
        objective=template.objective,
        status="active",
        created_by=user.id,
        template_id=template.id,
        icon=template.icon,
        color=template.color,
    )
    db.add(agent)
    await db.flush()
    await log_action(
        db,
        org_id=org.id,
        user_id=user.id,
        action="agent_from_template",
        metadata={"agent_id": str(agent.id), "template_id": template.id},
    )
    await db.commit()
    return AgentResponse.model_validate(agent)
