from collections.abc import AsyncGenerator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool

from app.config import settings

# Engine configuration depending on environment
async_engine_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,
}

if settings.APP_ENV == "test":
    async_engine_kwargs["poolclass"] = NullPool
else:
    async_engine_kwargs["poolclass"] = AsyncAdaptedQueuePool
    async_engine_kwargs["pool_size"] = 10
    async_engine_kwargs["max_overflow"] = 20

# Async engine for application runtime
async_engine = create_async_engine(
    settings.DATABASE_URL,
    **async_engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Synchronous engine for Alembic and migration scripts
sync_engine = create_engine(
    settings.DATABASE_URL_SYNC,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing an async database session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
