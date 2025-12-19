"""Main FastAPI application for LLM Generation service."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import generate, health
from .config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    logger.info("Starting LLM Generation service", service=settings.SERVICE_NAME)

    yield

    # Shutdown
    logger.info("Shutting down LLM Generation service")

    # Clean up service if initialized
    from .api.routes.generate import _service

    if _service:
        await _service.close()


app = FastAPI(
    title="LLM Generation Service",
    description="LLM-based text generation with citation support",
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
app.include_router(generate.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "status": "running",
    }
