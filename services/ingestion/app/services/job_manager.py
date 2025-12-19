"""Ingestion job management."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.core.models import IngestionJobModel
from services.ingestion.app.core.schemas import (
    IngestionJob,
    JobStatus,
    JobType,
)
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class JobManager:
    """Manage ingestion jobs and their lifecycle."""

    def __init__(self, db: AsyncSession):
        """Initialize job manager.

        Args:
            db: Database session
        """
        self.db = db

    async def create_job(
        self,
        job_type: JobType,
        source: str | None = None,
        query: str | None = None,
        document_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IngestionJob:
        """Create a new ingestion job.

        Args:
            job_type: Type of job
            source: Source identifier
            query: Search query (for search jobs)
            document_id: Document ID (for import jobs)
            metadata: Additional job metadata

        Returns:
            Created job
        """
        job_id = str(uuid.uuid4())

        job_model = IngestionJobModel(
            job_id=job_id,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # Default user for now
            job_type=job_type.value,
            status=JobStatus.PENDING.value,
            source=source,
            query=query,
            document_ids=[uuid.UUID(document_id)] if document_id else [],
            result_data=metadata or {},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        self.db.add(job_model)
        await self.db.commit()
        await self.db.refresh(job_model)

        logger.info(
            "job_created",
            job_id=job_id,
            job_type=job_type.value,
            source=source,
        )

        return self._to_schema(job_model)

    async def get_job(self, job_id: str) -> IngestionJob | None:
        """Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            Job or None
        """
        result = await self.db.execute(
            select(IngestionJobModel).where(IngestionJobModel.job_id == job_id)
        )
        job_model = result.scalar_one_or_none()

        if not job_model:
            return None

        return self._to_schema(job_model)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        error: str | None = None,
        result_count: int | None = None,
        metadata_updates: dict[str, Any] | None = None,
    ) -> IngestionJob | None:
        """Update job status.

        Args:
            job_id: Job identifier
            status: New status
            error: Error message (for failed jobs)
            result_count: Number of results (for completed jobs)
            metadata_updates: Additional metadata to merge

        Returns:
            Updated job or None
        """
        # Get current job
        result = await self.db.execute(
            select(IngestionJobModel).where(IngestionJobModel.job_id == job_id)
        )
        job_model = result.scalar_one_or_none()

        if not job_model:
            return None

        # Update fields
        job_model.status = status.value
        job_model.updated_at = datetime.now(timezone.utc)

        if error:
            job_model.error_message = error

        if result_count is not None:
            job_model.result_data = {**(job_model.result_data or {}), "result_count": result_count}

        if status == JobStatus.RUNNING and not job_model.started_at:
            job_model.started_at = datetime.now(timezone.utc)

        if status in (JobStatus.COMPLETED, JobStatus.FAILED):
            job_model.completed_at = datetime.now(timezone.utc)

        if metadata_updates:
            current_data = dict(job_model.result_data or {})
            current_data.update(metadata_updates)
            job_model.result_data = current_data

        await self.db.commit()
        await self.db.refresh(job_model)

        logger.info(
            "job_status_updated",
            job_id=job_id,
            status=status.value,
            error=error,
        )

        return self._to_schema(job_model)

    async def list_jobs(
        self,
        job_type: JobType | None = None,
        status: JobStatus | None = None,
        source: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[IngestionJob]:
        """List jobs with optional filters.

        Args:
            job_type: Filter by job type
            status: Filter by status
            source: Filter by source
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of jobs
        """
        query = select(IngestionJobModel)

        if job_type:
            query = query.where(IngestionJobModel.job_type == job_type.value)

        if status:
            query = query.where(IngestionJobModel.status == status.value)

        if source:
            query = query.where(IngestionJobModel.source == source)

        query = query.order_by(IngestionJobModel.created_at.desc())
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        job_models = result.scalars().all()

        return [self._to_schema(m) for m in job_models]

    async def get_pending_jobs(self, limit: int = 10) -> list[IngestionJob]:
        """Get pending jobs ready for processing.

        Args:
            limit: Maximum jobs to return

        Returns:
            List of pending jobs
        """
        result = await self.db.execute(
            select(IngestionJobModel)
            .where(IngestionJobModel.status == JobStatus.PENDING.value)
            .order_by(IngestionJobModel.created_at.asc())
            .limit(limit)
        )
        job_models = result.scalars().all()

        return [self._to_schema(m) for m in job_models]

    async def claim_job(self, job_id: str, worker_id: str) -> bool:
        """Claim a job for processing.

        Uses optimistic locking to prevent race conditions.

        Args:
            job_id: Job identifier
            worker_id: Worker claiming the job

        Returns:
            True if job was claimed
        """
        result = await self.db.execute(
            update(IngestionJobModel)
            .where(
                IngestionJobModel.job_id == job_id,
                IngestionJobModel.status == JobStatus.PENDING.value,
            )
            .values(
                status=JobStatus.RUNNING.value,
                started_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
                result_data=IngestionJobModel.result_data.concat({"worker_id": worker_id}),
            )
        )

        await self.db.commit()

        if result.rowcount > 0:
            logger.info(
                "job_claimed",
                job_id=job_id,
                worker_id=worker_id,
            )
            return True

        return False

    async def cancel_job(self, job_id: str) -> IngestionJob | None:
        """Cancel a pending or running job.

        Args:
            job_id: Job identifier

        Returns:
            Cancelled job or None
        """
        result = await self.db.execute(
            update(IngestionJobModel)
            .where(
                IngestionJobModel.job_id == job_id,
                IngestionJobModel.status.in_([
                    JobStatus.PENDING.value,
                    JobStatus.RUNNING.value,
                ]),
            )
            .values(
                status=JobStatus.CANCELLED.value,
                completed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(IngestionJobModel)
        )

        await self.db.commit()

        job_model = result.scalar_one_or_none()
        if job_model:
            logger.info("job_cancelled", job_id=job_id)
            return self._to_schema(job_model)

        return None

    async def cleanup_stale_jobs(self, stale_minutes: int = 60) -> int:
        """Reset stale running jobs to pending.

        Args:
            stale_minutes: Minutes before job is considered stale

        Returns:
            Number of jobs reset
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)

        result = await self.db.execute(
            update(IngestionJobModel)
            .where(
                IngestionJobModel.status == JobStatus.RUNNING.value,
                IngestionJobModel.started_at < cutoff,
            )
            .values(
                status=JobStatus.PENDING.value,
                started_at=None,
                updated_at=datetime.now(timezone.utc),
            )
        )

        await self.db.commit()

        count = result.rowcount
        if count > 0:
            logger.warning("stale_jobs_reset", count=count)

        return count

    def _to_schema(self, model: IngestionJobModel) -> IngestionJob:
        """Convert model to schema.

        Args:
            model: Database model

        Returns:
            Pydantic schema
        """
        return IngestionJob(
            job_id=model.job_id,
            user_id=model.user_id,
            job_type=model.job_type,
            status=model.status,
            source=model.source,
            query=model.query,
            progress=model.progress or {},
            total_items=model.total_items or 0,
            processed_items=model.processed_items or 0,
            result_data=model.result_data or {},
            error_message=model.error_message,
            document_ids=model.document_ids or [],
            upload_ids=model.upload_ids or [],
            created_at=model.created_at,
            updated_at=model.updated_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
        )
