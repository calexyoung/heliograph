"""Ingestion Service main application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.ingestion.app.api import api_router
from services.ingestion.app.api.deps import cleanup_dependencies
from services.ingestion.app.config import settings
from shared.utils.db import init_db, close_db
from shared.utils.logging import get_logger, setup_logging
from shared.utils.metrics import setup_metrics

# Setup logging
setup_logging(service_name="ingestion", log_level=settings.log_level)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("ingestion_service_starting")

    # Initialize database
    init_db(
        database_url=settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )

    # Setup metrics
    setup_metrics(app, service_name="ingestion")

    yield

    # Cleanup
    logger.info("ingestion_service_stopping")
    await cleanup_dependencies()
    await close_db()


app = FastAPI(
    title="HelioGraph Ingestion Service",
    description="Paper search and import service for HelioGraph RAG platform",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": "ingestion",
        "version": "0.1.0",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.ingestion.app.main:app",
        host="0.0.0.0",
        port=8002,
        reload=settings.debug,
    )
