from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workspace import Workspace


async def get_or_create_default_workspace(db: AsyncSession) -> Workspace:
    """Ensures a default primary workspace exists for single-user operation."""
    stmt = select(Workspace).order_by(Workspace.created_at.asc()).limit(1)
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()

    if not workspace:
        workspace = Workspace(
            name="Primary Workspace",
            slug="primary-workspace",
            description="Default single-user execution workspace for ASTRAVA.",
            settings_json={"theme": "light", "telemetry": False},
        )
        db.add(workspace)
        await db.flush()
        await db.refresh(workspace)

    return workspace
