"""Health check endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_processing.app.api.deps import get_db, get_qdrant_client, get_grobid_parser
from services.document_processing.app.embeddings.qdrant import QdrantClient
from services.document_processing.app.parsers.grobid import GrobidParser
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "service": "document-processing"}


@router.get("/ready")
async def readiness_check(
    db: AsyncSession = Depends(get_db),
    qdrant: QdrantClient = Depends(get_qdrant_client),
    grobid: GrobidParser = Depends(get_grobid_parser),
):
    """Readiness check including dependencies."""
    checks = {
        "database": False,
        "qdrant": False,
        "grobid": False,
    }

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.error("readiness_db_error", error=str(e))

    # Check Qdrant
    try:
        checks["qdrant"] = await qdrant.check_health()
    except Exception as e:
        logger.error("readiness_qdrant_error", error=str(e))

    # Check GROBID
    try:
        checks["grobid"] = await grobid.check_health()
    except Exception as e:
        logger.error("readiness_grobid_error", error=str(e))

    all_healthy = all(checks.values())

    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks,
    }


@router.get("/live")
async def liveness_check():
    """Liveness check."""
    return {"status": "alive"}
