"""Processing API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_processing.app.api.deps import get_db, get_orchestrator
from services.document_processing.app.core.models import ProcessingJobModel
from services.document_processing.app.core.schemas import (
    PipelineStage,
    ProcessingJob,
    ProcessingResult,
    ProcessingStatus,
    ReprocessRequest,
)
from services.document_processing.app.pipeline.orchestrator import PipelineOrchestrator
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.post("/reprocess", response_model=ProcessingResult)
async def reprocess_document(
    request: ReprocessRequest,
    background_tasks: BackgroundTasks,
    orchestrator: PipelineOrchestrator = Depends(get_orchestrator),
):
    """Reprocess a document through the pipeline.

    Use this to retry failed documents or re-index updated documents.
    """
    # Check if document is already being processed
    # (In production, would check processing lock)

    result = await orchestrator.reprocess_document(
        document_id=request.document_id,
        from_stage=request.from_stage,
    )

    return result


@router.get("/jobs/{job_id}", response_model=ProcessingJob)
async def get_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get processing job status."""
    result = await db.execute(
        select(ProcessingJobModel).where(ProcessingJobModel.job_id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ProcessingJob(
        job_id=job.job_id,
        document_id=job.document_id,
        status=ProcessingStatus(job.status),
        current_stage=PipelineStage(job.current_stage) if job.current_stage else None,
        stages_completed=[PipelineStage(s) for s in job.stages_completed] if job.stages_completed else [],
        stage_timings=job.stage_timings or {},
        retry_count=job.retry_count,
        error_message=job.error_message,
        worker_id=job.worker_id,
        metadata=job.metadata or {},
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/jobs", response_model=list[ProcessingJob])
async def list_jobs(
    status: ProcessingStatus | None = Query(None, description="Filter by status"),
    document_id: UUID | None = Query(None, description="Filter by document"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List processing jobs."""
    query = select(ProcessingJobModel)

    if status:
        query = query.where(ProcessingJobModel.status == status.value)

    if document_id:
        query = query.where(ProcessingJobModel.document_id == document_id)

    query = query.order_by(ProcessingJobModel.created_at.desc())
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    jobs = result.scalars().all()

    return [
        ProcessingJob(
            job_id=job.job_id,
            document_id=job.document_id,
            status=ProcessingStatus(job.status),
            current_stage=PipelineStage(job.current_stage) if job.current_stage else None,
            stages_completed=[PipelineStage(s) for s in job.stages_completed] if job.stages_completed else [],
            stage_timings=job.stage_timings or {},
            retry_count=job.retry_count,
            error_message=job.error_message,
            worker_id=job.worker_id,
            metadata=job.metadata or {},
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
        for job in jobs
    ]


@router.get("/jobs/document/{document_id}", response_model=list[ProcessingJob])
async def get_jobs_for_document(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all processing jobs for a document."""
    result = await db.execute(
        select(ProcessingJobModel)
        .where(ProcessingJobModel.document_id == document_id)
        .order_by(ProcessingJobModel.created_at.desc())
    )
    jobs = result.scalars().all()

    return [
        ProcessingJob(
            job_id=job.job_id,
            document_id=job.document_id,
            status=ProcessingStatus(job.status),
            current_stage=PipelineStage(job.current_stage) if job.current_stage else None,
            stages_completed=[PipelineStage(s) for s in job.stages_completed] if job.stages_completed else [],
            stage_timings=job.stage_timings or {},
            retry_count=job.retry_count,
            error_message=job.error_message,
            worker_id=job.worker_id,
            metadata=job.metadata or {},
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
        for job in jobs
    ]


@router.get("/stats")
async def get_processing_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get processing statistics."""
    from sqlalchemy import func

    # Count by status
    status_counts = {}
    for status in ProcessingStatus:
        result = await db.execute(
            select(func.count()).where(ProcessingJobModel.status == status.value)
        )
        status_counts[status.value] = result.scalar()

    # Average processing time for completed jobs
    result = await db.execute(
        select(func.avg(
            func.extract('epoch', ProcessingJobModel.completed_at) -
            func.extract('epoch', ProcessingJobModel.started_at)
        )).where(
            ProcessingJobModel.status == ProcessingStatus.COMPLETED.value,
            ProcessingJobModel.completed_at.isnot(None),
            ProcessingJobModel.started_at.isnot(None),
        )
    )
    avg_processing_time = result.scalar()

    return {
        "jobs_by_status": status_counts,
        "avg_processing_time_seconds": avg_processing_time,
    }
