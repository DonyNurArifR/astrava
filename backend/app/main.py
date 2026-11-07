import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.agents import router as agents_router
from app.api.v1.approvals import router as approvals_router
from app.api.v1.artifacts import project_artifacts_router
from app.api.v1.artifacts import router as artifacts_router
from app.api.v1.auth import router as auth_router
from app.api.v1.executions import router as executions_router
from app.api.v1.goals import router as goals_router
from app.api.v1.health import router as health_router
from app.api.v1.intelligence import router as intelligence_router
from app.api.v1.memories import router as memories_router
from app.api.v1.orchestrator import router as orchestrator_router
from app.api.v1.projects import router as projects_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.workflows import router as workflows_router
from app.config import settings
from app.core.auth import authenticate_request, public_route
from app.core.guard import SecurityGuardMiddleware
from app.core.security_config import security_warnings, validate_security_configuration
from app.logging_config import setup_logging
from app.providers.claude_code import terminate_all_active_processes

setup_logging(debug=settings.DEBUG)
logger = logging.getLogger("astrava")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to start with an unsafe security configuration (raises before serving).
    validate_security_configuration(settings)
    for warning in security_warnings(settings):
        logger.warning(warning)
    logger.info("Initializing %s backend in %s mode...", settings.APP_NAME, settings.APP_ENV)
    # Ensure artifact storage path exists
    settings.ARTIFACT_STORAGE_PATH.mkdir(parents=True, exist_ok=True)
    logger.info("Artifact storage verified at: %s", settings.ARTIFACT_STORAGE_PATH)
    yield
    logger.info("Shutting down %s backend and terminating active processes...", settings.APP_NAME)
    terminated = terminate_all_active_processes()
    if terminated:
        logger.info("Terminated %d active provider child process(es).", terminated)


# Docs are plain Starlette routes outside the global dependency, so they are exposed only in
# DEBUG mode (which validate_security_configuration refuses on non-loopback hosts).
app = FastAPI(
    title=settings.APP_NAME,
    description="ASTRAVA: AI Creation and Orchestration Platform — From vision to execution.",
    version="1.3.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    dependencies=[Depends(authenticate_request)],
)

# Guard is added before CORS so CORSMiddleware is the outer layer (guard sits inside CORS).
app.add_middleware(SecurityGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token", "X-ASTRAVA-OPERATOR-KEY"],
)

# API Routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(agents_router, prefix="/api/v1")
app.include_router(orchestrator_router, prefix="/api/v1")
app.include_router(projects_router, prefix="/api/v1")
app.include_router(tasks_router, prefix="/api/v1")
app.include_router(workflows_router, prefix="/api/v1")
app.include_router(executions_router, prefix="/api/v1")
app.include_router(approvals_router, prefix="/api/v1")
app.include_router(artifacts_router, prefix="/api/v1")
app.include_router(project_artifacts_router, prefix="/api/v1")
app.include_router(memories_router, prefix="/api/v1")
app.include_router(goals_router, prefix="/api/v1")
app.include_router(intelligence_router, prefix="/api/v1")


@app.get("/")
@public_route
async def root():
    return {
        "app": settings.APP_NAME,
        "tagline": settings.BRAND_TAGLINE,
        "status": "online",
        "docs": "/docs" if settings.DEBUG else None,
        "api_v1": "/api/v1/healthz",
    }
