import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.health import router as health_router
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


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "tagline": settings.BRAND_TAGLINE,
        "status": "online",
        "docs": "/docs",
        "api_v1": "/api/v1/healthz",
    }
