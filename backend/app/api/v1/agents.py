from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.project import StudioType
from app.schemas.agent import AgentCreate, AgentRead, AgentStatusUpdate, AgentUpdate
from app.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agent Registry"])


@router.get("", response_model=list[AgentRead])
async def list_agents(
    studio_type: StudioType | None = Query(None, description="Filter by studio type (saas/media)"),
    is_enabled: bool | None = Query(None, description="Filter by enabled status"),
    db: AsyncSession = Depends(get_db),
) -> list[AgentRead]:
    agents = await AgentService.list_agents(db, studio_type=studio_type, is_enabled=is_enabled)
    # If no agents exist in database, seed them automatically
    if not agents:
        await AgentService.seed_default_agents(db)
        agents = await AgentService.list_agents(db, studio_type=studio_type, is_enabled=is_enabled)
    return [AgentRead.model_validate(a) for a in agents]


@router.post("/seed", status_code=status.HTTP_200_OK)
async def seed_agents(
    db: AsyncSession = Depends(get_db),
) -> dict[str, str | int]:
    count = await AgentService.seed_default_agents(db)
    return {"message": "Default agents seeded successfully", "new_agents_count": count}


@router.get("/{identifier}", response_model=AgentRead)
async def get_agent(
    identifier: str,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    agent = await AgentService.get_by_id_or_slug(db, identifier)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{identifier}' not found in registry",
        )
    return AgentRead.model_validate(agent)


@router.post("", response_model=AgentRead, status_code=status.HTTP_201_CREATED)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    existing = await AgentService.get_by_id_or_slug(db, payload.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent with slug '{payload.slug}' already exists",
        )
    agent = await AgentService.create_agent(db, payload)
    return AgentRead.model_validate(agent)


@router.patch("/{identifier}/status", response_model=AgentRead)
async def update_agent_status(
    identifier: str,
    payload: AgentStatusUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    agent = await AgentService.get_by_id_or_slug(db, identifier)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{identifier}' not found in registry",
        )
    updated = await AgentService.set_agent_status(db, agent, payload.is_enabled)
    return AgentRead.model_validate(updated)


@router.put("/{identifier}", response_model=AgentRead)
async def update_agent(
    identifier: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
) -> AgentRead:
    agent = await AgentService.get_by_id_or_slug(db, identifier)
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{identifier}' not found in registry",
        )
    updated = await AgentService.update_agent(db, agent, payload)
    return AgentRead.model_validate(updated)
