import os

import pytest

from app.config import settings

os.environ["APP_ENV"] = "test"
settings.APP_ENV = "test"


@pytest.fixture(autouse=True)
async def cleanup_db_connections():
    yield
    from app.db.session import async_engine

    await async_engine.dispose()


@pytest.fixture
async def db_session():
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session
