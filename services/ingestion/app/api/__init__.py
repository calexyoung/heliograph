"""Ingestion API routes."""

from fastapi import APIRouter

from services.ingestion.app.api.routes import health, import_routes, jobs, search, upload

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(import_routes.router, prefix="/import", tags=["import"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(upload.router, prefix="/upload", tags=["upload"])

__all__ = ["api_router"]
