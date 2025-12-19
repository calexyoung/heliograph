"""Health check routes for Knowledge Extraction service."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    version: str = "0.1.0"


class ReadyResponse(BaseModel):
    """Readiness check response."""

    status: str
    postgres: str
    neo4j: str


@router.get("/health", response_model=HealthResponse)
async def health_check(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        service=settings.SERVICE_NAME,
    )


@router.get("/ready", response_model=ReadyResponse)
async def readiness_check() -> ReadyResponse:
    """Readiness check endpoint."""
    # In production, these would actually check connections
    return ReadyResponse(
        status="ready",
        postgres="connected",
        neo4j="connected",
    )
