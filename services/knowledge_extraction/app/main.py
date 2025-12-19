"""Main FastAPI application for Knowledge Extraction service."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.deps import close_neo4j_client, get_neo4j_client
from .api.routes import extraction, graph, health
from .config import get_settings

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Knowledge Extraction service", service=settings.SERVICE_NAME)

    # Initialize Neo4j connection
    try:
        neo4j = await get_neo4j_client()
        await neo4j.setup_schema()
        logger.info("Neo4j connection established")
    except Exception as e:
        logger.error("Failed to connect to Neo4j", error=str(e))

    yield

    # Shutdown
    logger.info("Shutting down Knowledge Extraction service")
    await close_neo4j_client()


app = FastAPI(
    title="Knowledge Extraction Service",
    description="Entity and relationship extraction with knowledge graph construction",
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
app.include_router(extraction.router, prefix="/api/v1")
app.include_router(graph.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    """Root endpoint."""
    return {
        "service": settings.SERVICE_NAME,
        "version": "0.1.0",
        "status": "running",
    }
