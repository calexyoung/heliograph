"""Health check routes for Query Orchestrator service."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
    )
