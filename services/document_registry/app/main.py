"""Document Registry Service - FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from services.document_registry.app.api.routes import router
from services.document_registry.app.api.schemas import ErrorResponse
from services.document_registry.app.config import get_settings
from services.document_registry.app.middleware.idempotency import IdempotencyMiddleware
from services.document_registry.app.middleware.logging import RequestLoggingMiddleware
from services.document_registry.app.middleware.rate_limit import RateLimitMiddleware
from shared.utils.db import close_db, init_db
from shared.utils.logging import configure_logging, get_logger, get_correlation_id, set_correlation_id
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

# Add CORS middleware (all settings from environment config)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Add rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=settings.rate_limit_requests_per_minute,
    burst=settings.rate_limit_burst,
    enabled=settings.rate_limit_enabled,
    settings_getter=get_settings,  # Allow dynamic settings override in tests
)

# Add idempotency middleware (for POST/PATCH requests with Idempotency-Key header)
app.add_middleware(IdempotencyMiddleware)

# Add request logging middleware (structured logging with context)
app.add_middleware(
    RequestLoggingMiddleware,
    exclude_paths=["/registry/health", "/registry/ready", "/metrics"],
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


def _get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _get_request_context(request: Request) -> dict:
    """Build request context for logging."""
    return {
        "path": request.url.path,
        "method": request.method,
        "query_params": str(request.query_params) if request.query_params else None,
        "client_ip": _get_client_ip(request),
        "user_agent": request.headers.get("User-Agent"),
        "content_type": request.headers.get("Content-Type"),
        "content_length": request.headers.get("Content-Length"),
        "correlation_id": get_correlation_id(),
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    correlation_id = get_correlation_id()
    request_context = _get_request_context(request)

    logger.exception(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        **request_context,
    )

    error_response = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="An internal error occurred",
        correlation_id=correlation_id,
    )
    return JSONResponse(
        status_code=500,
        content=error_response.model_dump(exclude_none=True),
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
