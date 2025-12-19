"""API Gateway - FastAPI application entry point."""

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi

from services.api_gateway.app.api import (
    auth_router,
    files_router,
    health_router,
    preferences_router,
    proxy_router,
    realtime_router,
    upload_router,
)
from services.api_gateway.app.config import get_settings
from services.api_gateway.app.middleware.correlation import CorrelationMiddleware
from services.api_gateway.app.realtime.pubsub import PubSubManager
from shared.utils.db import close_db, init_db
from shared.utils.logging import configure_logging, get_logger
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

    # Initialize database
    init_db(
        database_url=settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )
    logger.info("database_initialized")

    # Initialize Redis
    try:
        redis_client = redis.from_url(settings.redis_url)
        app.state.redis = redis_client
        app.state.pubsub = PubSubManager(redis_client)
        logger.info("redis_initialized")
    except Exception as e:
        logger.warning("redis_init_failed", error=str(e))
        app.state.redis = None
        app.state.pubsub = None

    yield

    # Shutdown
    logger.info("shutting_down_service")

    if app.state.redis:
        await app.state.redis.close()

    await close_db()
    logger.info("service_shutdown_complete")


def custom_openapi():
    """Generate custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title="HelioGraph API Gateway",
        version="0.1.0",
        description="""
## HelioGraph RAG API

The API Gateway provides a unified interface to the HelioGraph Research Intelligence Platform.

### Authentication

All API endpoints (except health checks) require authentication via one of:

1. **Bearer Token**: Include `Authorization: Bearer <token>` header
2. **API Key**: Include `X-API-Key: <key>` header

### Rate Limiting

Default rate limits:
- **Per user**: 60 requests/minute
- **Per API key**: Configurable per key

Rate limit headers are included in all responses:
- `X-RateLimit-Limit`: Maximum requests allowed
- `X-RateLimit-Remaining`: Requests remaining in window
- `X-RateLimit-Reset`: Unix timestamp when limit resets

### Error Responses

All errors follow a consistent format:

```json
{
    "detail": "Error message",
    "error_code": "ERROR_CODE"
}
```

### Real-time Updates

For long-running operations (document processing, queries):

- **WebSocket**: `ws://host/api/ws/jobs/{job_id}?token=<access_token>`
- **SSE**: `GET /api/events/jobs/{job_id}`
        """,
        routes=app.routes,
    )

    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "bearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        },
        "apiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
        },
    }

    # Apply security globally
    openapi_schema["security"] = [
        {"bearerAuth": []},
        {"apiKeyAuth": []},
    ]

    app.openapi_schema = openapi_schema
    return app.openapi_schema


app = FastAPI(
    title="HelioGraph API Gateway",
    description="Unified API Gateway for HelioGraph RAG platform",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Override OpenAPI schema
app.openapi = custom_openapi

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add correlation ID middleware
app.add_middleware(CorrelationMiddleware)

# Add metrics middleware
app.add_middleware(MetricsMiddleware)

# Note: Rate limiting middleware would be added here with Redis client
# app.add_middleware(RateLimitMiddleware, redis_client=redis_client, ...)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler for unhandled errors."""
    logger.exception("unhandled_exception", error=str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred",
            "error_code": "INTERNAL_ERROR",
        },
    )


# Include routers
# Note: nginx strips /api/ prefix, so routes are mounted at root
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(files_router)
app.include_router(upload_router)
app.include_router(preferences_router)
app.include_router(proxy_router)
app.include_router(realtime_router)

# Add metrics endpoint
app.add_route("/metrics", metrics_endpoint)


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": settings.service_name,
        "version": "0.1.0",
        "docs": "/docs",
        "redoc": "/redoc",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "services.api_gateway.app.main:app",
        host="0.0.0.0",
        port=8080,
        reload=settings.debug,
    )
