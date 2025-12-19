"""Health check and status routes."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from services.api_gateway.app.middleware.auth import get_db
from services.api_gateway.app.routing.proxy import ServiceProxy

router = APIRouter(tags=["Health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "unhealthy"]
    service: str
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    checks: dict[str, bool]


class ServiceStatus(BaseModel):
    """Backend service status."""

    name: str
    state: str
    failures: int
    successes: int


class StatusResponse(BaseModel):
    """Full system status response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    gateway: HealthResponse
    backend_services: list[ServiceStatus]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Basic health check - returns if the service is running."""
    return HealthResponse(
        status="healthy",
        service="api-gateway",
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(
    db: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """Readiness check - verifies dependencies are available."""
    checks = {}

    # Check database
    try:
        await db.execute("SELECT 1")
        checks["database"] = True
    except Exception:
        checks["database"] = False

    # TODO: Check Redis when configured
    checks["redis"] = True  # Placeholder

    ready = all(checks.values())
    return ReadinessResponse(ready=ready, checks=checks)


@router.get("/status", response_model=StatusResponse)
async def system_status() -> StatusResponse:
    """Get full system status including backend services."""
    proxy = ServiceProxy()
    circuit_states = proxy.get_circuit_states()

    backend_services = [
        ServiceStatus(
            name=name,
            state=state["state"],
            failures=state["failures"],
            successes=state["successes"],
        )
        for name, state in circuit_states.items()
    ]

    # Determine overall status
    open_circuits = sum(1 for s in backend_services if s.state == "open")
    if open_circuits == 0:
        status = "healthy"
    elif open_circuits < len(backend_services):
        status = "degraded"
    else:
        status = "unhealthy"

    return StatusResponse(
        status=status,
        gateway=HealthResponse(status="healthy", service="api-gateway"),
        backend_services=backend_services,
    )
