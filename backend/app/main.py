import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.approvals import router as approvals_router
from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.executions import router as executions_router
from app.api.v1.health import router as health_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.workflows import router as workflows_router
from app.config import settings
from app.logging_config import setup_logging

setup_logging(debug=settings.DEBUG)
logger = logging.getLogger("astrava")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing %s backend in %s mode...", settings.APP_NAME, settings.APP_ENV)
    # Ensure artifact storage path exists
    settings.ARTIFACT_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    logger.info("Artifact storage verified at: %s", settings.ARTIFACT_STORAGE_PATH)
    yield
    logger.info("Shutting down %s backend...", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description="ASTRAVA: AI Creation and Orchestration Platform — From vision to execution.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(executions_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(intelligence_router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "tagline": settings.BRAND_TAGLINE,
        "status": "online",
        "docs": "/docs",
        "api_v1": "/api/v1/healthz",
    }
