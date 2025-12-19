"""API routes for API Gateway."""

from services.api_gateway.app.api.auth import router as auth_router
from services.api_gateway.app.api.files import router as files_router
from services.api_gateway.app.api.upload import router as upload_router
from services.api_gateway.app.api.proxy import router as proxy_router
from services.api_gateway.app.api.realtime import router as realtime_router
from services.api_gateway.app.api.health import router as health_router
from services.api_gateway.app.api.preferences import router as preferences_router

__all__ = [
    "auth_router",
    "files_router",
    "upload_router",
    "proxy_router",
    "realtime_router",
    "health_router",
    "preferences_router",
]
