"""Job management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.api.deps import get_db
from services.ingestion.app.core.schemas import (
    IngestionJob,
    JobStatus,
    JobType,
)
from services.ingestion.app.services.job_manager import JobManager
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


async def get_job_manager(db: AsyncSession = Depends(get_db)) -> JobManager:
    """Get job manager instance."""
    return JobManager(db)


@router.get("/{job_id}", response_model=IngestionJob)
async def get_job(
    job_id: str,
    job_manager: JobManager = Depends(get_job_manager),
):
    """Get job by ID."""
    job = await job_manager.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return job


@router.get("", response_model=list[IngestionJob])
async def list_jobs(
    job_type: JobType | None = Query(None, description="Filter by job type"),
    status: JobStatus | None = Query(None, description="Filter by status"),
    source: str | None = Query(None, description="Filter by source"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    job_manager: JobManager = Depends(get_job_manager),
):
    """List jobs with optional filters."""
    return await job_manager.list_jobs(
        job_type=job_type,
        status=status,
        source=source,
        limit=limit,
        offset=offset,
    )


@router.post("/{job_id}/cancel", response_model=IngestionJob)
async def cancel_job(
    job_id: str,
    job_manager: JobManager = Depends(get_job_manager),
):
    """Cancel a pending or running job."""
    job = await job_manager.cancel_job(job_id)

    if not job:
        raise HTTPException(
            status_code=400,
            detail="Job not found or cannot be cancelled",
        )

    return job


@router.get("/pending/count")
async def get_pending_count(
    job_manager: JobManager = Depends(get_job_manager),
):
    """Get count of pending jobs."""
    jobs = await job_manager.get_pending_jobs(limit=1000)
    return {"count": len(jobs)}


@router.post("/cleanup/stale")
async def cleanup_stale_jobs(
    stale_minutes: int = Query(60, ge=5, le=1440, description="Minutes before job is stale"),
    job_manager: JobManager = Depends(get_job_manager),
):
    """Reset stale running jobs to pending.

    Admin endpoint for cleaning up stuck jobs.
    """
    count = await job_manager.cleanup_stale_jobs(stale_minutes=stale_minutes)
    return {"reset_count": count}
