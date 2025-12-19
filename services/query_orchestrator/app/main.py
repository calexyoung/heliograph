"""Main FastAPI application for Query Orchestrator service."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import health, query
from .config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Query Orchestrator service", service=settings.SERVICE_NAME)

    yield

    # Shutdown
    logger.info("Shutting down Query Orchestrator service")

    # Clean up orchestrator if initialized
    from .api.routes.query import _orchestrator

    if _orchestrator:
        await _orchestrator.close()


app = FastAPI(
    title="Query Orchestrator Service",
    description="RAG query processing with vector and graph-augmented retrieval",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router, prefix="/api/v1")
app.include_router(query.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "status": "running",
    }
