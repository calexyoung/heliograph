"""Document Processing API routes."""

from fastapi import APIRouter

from services.document_processing.app.api.routes import health, processing, chunks

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(processing.router, prefix="/processing", tags=["processing"])
api_router.include_router(chunks.router, prefix="/chunks", tags=["chunks"])

__all__ = ["api_router"]
