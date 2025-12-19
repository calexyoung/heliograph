"""Tests for job management."""

import pytest
from datetime import datetime, timezone

from services.ingestion.app.core.schemas import JobStatus, JobType
from services.ingestion.app.services.job_manager import JobManager


class TestJobManager:
    """Tests for job manager."""

    @pytest.mark.asyncio
    async def test_create_job(self, test_session):
        """Test creating a new job."""
        manager = JobManager(test_session)

        job = await manager.create_job(
            job_type=JobType.IMPORT,
            source="crossref",
            metadata={"doi": "10.1234/test"},
        )

        assert job.job_id is not None
        assert job.job_type == JobType.IMPORT
        assert job.status == JobStatus.PENDING
        assert job.source == "crossref"
        assert job.metadata["doi"] == "10.1234/test"

    @pytest.mark.asyncio
    async def test_get_job(self, test_session):
        """Test retrieving a job."""
        manager = JobManager(test_session)

        created = await manager.create_job(
            job_type=JobType.SEARCH,
            query="solar physics",
        )

        retrieved = await manager.get_job(created.job_id)

        assert retrieved is not None
        assert retrieved.job_id == created.job_id
        assert retrieved.query == "solar physics"

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, test_session):
        """Test retrieving non-existent job."""
        manager = JobManager(test_session)

        job = await manager.get_job("nonexistent-id")

        assert job is None

    @pytest.mark.asyncio
    async def test_update_status_to_running(self, test_session):
        """Test updating job status to running."""
        manager = JobManager(test_session)

        job = await manager.create_job(job_type=JobType.IMPORT)

        updated = await manager.update_status(
            job.job_id,
            JobStatus.RUNNING,
        )

        assert updated.status == JobStatus.RUNNING
        assert updated.started_at is not None

    @pytest.mark.asyncio
    async def test_update_status_to_completed(self, test_session):
        """Test updating job status to completed."""
        manager = JobManager(test_session)

        job = await manager.create_job(job_type=JobType.IMPORT)

        updated = await manager.update_status(
            job.job_id,
            JobStatus.COMPLETED,
            result_count=5,
        )

        assert updated.status == JobStatus.COMPLETED
        assert updated.completed_at is not None
        assert updated.result_count == 5

    @pytest.mark.asyncio
    async def test_update_status_to_failed(self, test_session):
        """Test updating job status to failed."""
        manager = JobManager(test_session)

        job = await manager.create_job(job_type=JobType.IMPORT)

        updated = await manager.update_status(
            job.job_id,
            JobStatus.FAILED,
            error="Connection timeout",
        )

        assert updated.status == JobStatus.FAILED
        assert updated.error == "Connection timeout"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_list_jobs_all(self, test_session):
        """Test listing all jobs."""
        manager = JobManager(test_session)

        # Create multiple jobs
        await manager.create_job(job_type=JobType.IMPORT, source="crossref")
        await manager.create_job(job_type=JobType.SEARCH, query="test")
        await manager.create_job(job_type=JobType.IMPORT, source="arxiv")

        jobs = await manager.list_jobs()

        assert len(jobs) == 3

    @pytest.mark.asyncio
    async def test_list_jobs_by_type(self, test_session):
        """Test listing jobs filtered by type."""
        manager = JobManager(test_session)

        await manager.create_job(job_type=JobType.IMPORT)
        await manager.create_job(job_type=JobType.SEARCH)
        await manager.create_job(job_type=JobType.IMPORT)

        jobs = await manager.list_jobs(job_type=JobType.IMPORT)

        assert len(jobs) == 2
        assert all(j.job_type == JobType.IMPORT for j in jobs)

    @pytest.mark.asyncio
    async def test_list_jobs_by_status(self, test_session):
        """Test listing jobs filtered by status."""
        manager = JobManager(test_session)

        job1 = await manager.create_job(job_type=JobType.IMPORT)
        job2 = await manager.create_job(job_type=JobType.IMPORT)
        await manager.update_status(job1.job_id, JobStatus.COMPLETED)

        pending_jobs = await manager.list_jobs(status=JobStatus.PENDING)
        completed_jobs = await manager.list_jobs(status=JobStatus.COMPLETED)

        assert len(pending_jobs) == 1
        assert len(completed_jobs) == 1

    @pytest.mark.asyncio
    async def test_get_pending_jobs(self, test_session):
        """Test getting pending jobs."""
        manager = JobManager(test_session)

        job1 = await manager.create_job(job_type=JobType.IMPORT)
        job2 = await manager.create_job(job_type=JobType.IMPORT)
        job3 = await manager.create_job(job_type=JobType.IMPORT)

        # Mark one as running
        await manager.update_status(job1.job_id, JobStatus.RUNNING)

        pending = await manager.get_pending_jobs()

        assert len(pending) == 2
        assert all(j.status == JobStatus.PENDING for j in pending)

    @pytest.mark.asyncio
    async def test_cancel_job(self, test_session):
        """Test cancelling a job."""
        manager = JobManager(test_session)

        job = await manager.create_job(job_type=JobType.IMPORT)

        cancelled = await manager.cancel_job(job.job_id)

        assert cancelled is not None
        assert cancelled.status == JobStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_completed_job_fails(self, test_session):
        """Test cancelling a completed job fails."""
        manager = JobManager(test_session)

        job = await manager.create_job(job_type=JobType.IMPORT)
        await manager.update_status(job.job_id, JobStatus.COMPLETED)

        cancelled = await manager.cancel_job(job.job_id)

        assert cancelled is None

    @pytest.mark.asyncio
    async def test_metadata_updates(self, test_session):
        """Test metadata updates on status change."""
        manager = JobManager(test_session)

        job = await manager.create_job(
            job_type=JobType.IMPORT,
            metadata={"initial": "value"},
        )

        updated = await manager.update_status(
            job.job_id,
            JobStatus.COMPLETED,
            metadata_updates={"new_key": "new_value"},
        )

        assert updated.metadata["initial"] == "value"
        assert updated.metadata["new_key"] == "new_value"
