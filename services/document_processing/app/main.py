"""Document Processing Service main application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.document_processing.app.api import api_router
from services.document_processing.app.api.deps import cleanup_dependencies
from services.document_processing.app.config import settings
from shared.utils.db import init_db, close_db
from shared.utils.logging import get_logger, setup_logging
from shared.utils.metrics import setup_metrics

# Setup logging
setup_logging(service_name="document-processing", log_level=settings.LOG_LEVEL)
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("document_processing_service_starting")

    # Initialize database
    init_db(
        database_url=settings.DATABASE_URL,
        pool_size=5,
        max_overflow=10,
    )
    logger.info("database_initialized")

    # Setup metrics
    if settings.METRICS_ENABLED:
        setup_metrics(app, service_name="document-processing")

    yield

    # Cleanup
    logger.info("document_processing_service_stopping")
    await cleanup_dependencies()
    await close_db()


app = FastAPI(
    title="HelioGraph Document Processing Service",
    description="Document processing pipeline for PDF parsing, chunking, and embedding",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
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
        "service": "document-processing",
        "version": "0.1.0",
        "status": "running",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.document_processing.app.main:app",
        host="0.0.0.0",
        port=8003,
        reload=settings.DEBUG,
    )
