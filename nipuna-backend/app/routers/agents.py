from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_org, get_current_user
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentResponse, AgentUpdate
from app.utils.audit import log_action

router = APIRouter(prefix="/agents", tags=["agents"])


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
