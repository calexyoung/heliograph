"""Health check endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.api.deps import get_db
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "service": "ingestion"}


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check including dependencies."""
    checks = {
        "database": False,
    }

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("readiness_db_error", error=str(e))

    all_healthy = all(checks.values())

    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
    }


@router.get("/live")
async def liveness_check():
    """Liveness check."""
    return {"status": "alive"}
