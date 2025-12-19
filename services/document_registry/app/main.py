"""Document Registry Service - FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.document_registry.app.api.routes import router
from services.document_registry.app.config import get_settings
from shared.utils.db import close_db, init_db
from shared.utils.logging import configure_logging, get_logger, set_correlation_id
from shared.utils.metrics import MetricsMiddleware, metrics_endpoint

settings = get_settings()

# Configure logging
configure_logging(
    service_name=settings.service_name,
    log_level=settings.log_level,
    json_format=settings.log_json,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("starting_service", service=settings.service_name)
    init_db(
        database_url=settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        echo=settings.db_echo,
    )
    logger.info("database_initialized")

    yield

    # Shutdown
    logger.info("shutting_down_service")
    await close_db()
    logger.info("service_shutdown_complete")


app = FastAPI(
    title="Document Registry Service",
    description="Canonical metadata store and deduplication service for HelioGraph RAG",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add metrics middleware
app.add_middleware(MetricsMiddleware)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """Extract or generate correlation ID for each request."""
    correlation_id = request.headers.get("X-Correlation-ID")
    set_correlation_id(correlation_id)
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id or ""
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "error_code": "INTERNAL_ERROR",
            "message": "An internal error occurred",
        },
    )


# Include routes
app.include_router(router, prefix=settings.api_prefix)

# Add metrics endpoint
app.add_route("/metrics", metrics_endpoint)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "service": settings.service_name,
        "version": "0.1.0",
        "docs": "/docs",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.document_registry.app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
    )
