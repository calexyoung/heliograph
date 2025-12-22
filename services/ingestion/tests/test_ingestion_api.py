"""Tests for API endpoints."""

import pytest
from unittest.mock import AsyncMock, patch

from services.ingestion.app.core.schemas import (
    SearchResponse,
    SearchResult,
    SourceStatus,
)
from services.ingestion.app.main import app
from services.ingestion.app.api import deps
from shared.schemas.author import AuthorSchema


class TestHealthEndpoints:
    """Tests for health check endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Test basic health check."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "ingestion"

    @pytest.mark.asyncio
    async def test_liveness_check(self, client):
        """Test liveness check."""
        response = await client.get("/api/v1/health/live")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"


class TestSearchEndpoints:
    """Tests for search endpoints."""

    @pytest.fixture
    def mock_search_response(self):
        """Create mock search response."""
        return SearchResponse(
            query="solar physics",
            results=[
                SearchResult(
                    source="crossref",
                    external_id="10.1234/test",
                    title="Test Paper",
                    authors=[AuthorSchema(given_name="John", family_name="Smith")],
                    year=2024,
                    doi="10.1234/test",
                )
            ],
            total_results=1,
            sources_searched=["crossref"],
            source_statuses={
                "crossref": SourceStatus(
                    source="crossref",
                    success=True,
                    result_count=1,
                )
            },
        )

    @pytest.mark.asyncio
    async def test_search_post(self, client, mock_search_response):
        """Test POST search endpoint."""
        mock_orchestrator = AsyncMock()
        mock_orchestrator.search.return_value = mock_search_response

        app.dependency_overrides[deps.get_search_orchestrator] = lambda: mock_orchestrator

        try:
            response = await client.post(
                "/api/v1/search",
                json={
                    "query": "solar physics",
                    "limit": 10,
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "solar physics"
            assert len(data["results"]) == 1
        finally:
            app.dependency_overrides.pop(deps.get_search_orchestrator, None)

    @pytest.mark.asyncio
    async def test_search_get(self, client, mock_search_response):
        """Test GET search endpoint."""
        mock_orchestrator = AsyncMock()
        mock_orchestrator.search.return_value = mock_search_response

        app.dependency_overrides[deps.get_search_orchestrator] = lambda: mock_orchestrator

        try:
            response = await client.get(
                "/api/v1/search",
                params={"query": "solar physics", "limit": 10},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["query"] == "solar physics"
        finally:
            app.dependency_overrides.pop(deps.get_search_orchestrator, None)

    @pytest.mark.asyncio
    async def test_list_sources(self, client):
        """Test list sources endpoint."""
        response = await client.get("/api/v1/search/sources")

        assert response.status_code == 200
        data = response.json()
        assert "sources" in data
        assert len(data["sources"]) == 4

        source_names = [s["name"] for s in data["sources"]]
        assert "crossref" in source_names
        assert "semantic_scholar" in source_names
        assert "arxiv" in source_names
        assert "scixplorer" in source_names


class TestJobEndpoints:
    """Tests for job management endpoints."""

    @pytest.fixture
    def mock_job(self):
        """Create mock job."""
        from uuid import uuid4
        from datetime import datetime
        from services.ingestion.app.core.schemas import IngestionJob

        return IngestionJob(
            job_id=uuid4(),
            user_id=uuid4(),
            job_type="import",
            status="pending",
            source="crossref",
            query="solar physics",
            progress={},
            total_items=10,
            processed_items=0,
            result_data={},
            error_message=None,
            document_ids=[],
            upload_ids=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    @pytest.fixture
    def mock_job_manager(self):
        """Create mock job manager."""
        return AsyncMock()

    @pytest.mark.asyncio
    async def test_list_jobs_empty(self, client, test_session):
        """Test listing jobs when empty."""
        response = await client.get("/api/v1/jobs")

        assert response.status_code == 200
        data = response.json()
        assert data == []

    @pytest.mark.asyncio
    async def test_get_job_not_found(self, client):
        """Test getting non-existent job."""
        response = await client.get("/api/v1/jobs/nonexistent-id")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_job_success(self, client, mock_job):
        """Test getting job by ID."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.get_job.return_value = mock_job

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.get(f"/api/v1/jobs/{mock_job.job_id}")

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == str(mock_job.job_id)
            assert data["job_type"] == "import"
            assert data["status"] == "pending"
            assert data["source"] == "crossref"
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_list_jobs_success(self, client, mock_job):
        """Test listing jobs with results."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.list_jobs.return_value = [mock_job, mock_job]

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/jobs")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_list_jobs_with_filters(self, client, mock_job):
        """Test listing jobs with filters."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.list_jobs.return_value = [mock_job]

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.get(
                "/api/v1/jobs",
                params={
                    "job_type": "import",
                    "status": "pending",
                    "source": "crossref",
                    "limit": 25,
                    "offset": 10,
                },
            )

            assert response.status_code == 200
            mock_manager.list_jobs.assert_called_once_with(
                job_type="import",
                status="pending",
                source="crossref",
                limit=25,
                offset=10,
            )
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_cancel_job_success(self, client, mock_job):
        """Test cancelling a job."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        cancelled_job = mock_job.model_copy()
        cancelled_job.status = "cancelled"

        mock_manager = AsyncMock()
        mock_manager.cancel_job.return_value = cancelled_job

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.post(f"/api/v1/jobs/{mock_job.job_id}/cancel")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "cancelled"
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_cancel_job_not_found(self, client):
        """Test cancelling non-existent job."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.cancel_job.return_value = None

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/jobs/nonexistent-id/cancel")

            assert response.status_code == 400
            assert "cannot be cancelled" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_get_pending_count(self, client, mock_job):
        """Test getting pending job count."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.get_pending_jobs.return_value = [mock_job, mock_job, mock_job]

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/jobs/pending/count")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 3
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_get_pending_count_zero(self, client):
        """Test getting pending count when no pending jobs."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.get_pending_jobs.return_value = []

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/jobs/pending/count")

            assert response.status_code == 200
            data = response.json()
            assert data["count"] == 0
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs(self, client):
        """Test cleanup stale jobs endpoint."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.cleanup_stale_jobs.return_value = 5

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/jobs/cleanup/stale")

            assert response.status_code == 200
            data = response.json()
            assert data["reset_count"] == 5
            mock_manager.cleanup_stale_jobs.assert_called_once_with(stale_minutes=60)
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs_custom_minutes(self, client):
        """Test cleanup stale jobs with custom stale_minutes."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.cleanup_stale_jobs.return_value = 2

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/jobs/cleanup/stale",
                params={"stale_minutes": 120},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["reset_count"] == 2
            mock_manager.cleanup_stale_jobs.assert_called_once_with(stale_minutes=120)
        finally:
            app.dependency_overrides.pop(get_job_manager, None)

    @pytest.mark.asyncio
    async def test_cleanup_stale_jobs_none_reset(self, client):
        """Test cleanup stale jobs when no jobs are stale."""
        from services.ingestion.app.api.routes.jobs import get_job_manager

        mock_manager = AsyncMock()
        mock_manager.cleanup_stale_jobs.return_value = 0

        app.dependency_overrides[get_job_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/jobs/cleanup/stale")

            assert response.status_code == 200
            data = response.json()
            assert data["reset_count"] == 0
        finally:
            app.dependency_overrides.pop(get_job_manager, None)


class TestUploadEndpoints:
    """Tests for upload endpoints."""

    @pytest.mark.asyncio
    async def test_upload_pdf_success(self, client):
        """Test successful PDF upload."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_file.return_value = {
            "success": True,
            "s3_key": "documents/doc-123/abc123.pdf",
            "content_hash": "abc123def456",
            "size_bytes": 12345,
            "page_count": 10,
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            # Create a mock PDF file
            pdf_content = b"%PDF-1.4 test content"
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", pdf_content, "application/pdf")},
            )

            assert response.status_code == 200
            data = response.json()
            assert "document_id" in data
            assert data["s3_key"] == "documents/doc-123/abc123.pdf"
            assert data["content_hash"] == "abc123def456"
            assert data["size_bytes"] == 12345
            assert data["page_count"] == 10
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_pdf_with_document_id(self, client):
        """Test PDF upload with provided document ID."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_file.return_value = {
            "success": True,
            "s3_key": "documents/my-doc-id/abc123.pdf",
            "content_hash": "abc123",
            "size_bytes": 1000,
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            pdf_content = b"%PDF-1.4 test content"
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", pdf_content, "application/pdf")},
                data={"document_id": "my-doc-id"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["document_id"] == "my-doc-id"
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_pdf_invalid_content_type(self, client):
        """Test upload fails with non-PDF content type and extension."""
        mock_handler = AsyncMock()

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.txt", b"not a pdf", "text/plain")},
            )

            assert response.status_code == 400
            assert "PDF" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_pdf_allowed_with_pdf_extension(self, client):
        """Test upload allowed when content type wrong but extension is .pdf."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_file.return_value = {
            "success": True,
            "s3_key": "documents/doc-123/abc123.pdf",
            "content_hash": "abc123",
            "size_bytes": 1000,
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", b"%PDF-1.4", "application/octet-stream")},
            )

            assert response.status_code == 200
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_pdf_handler_failure(self, client):
        """Test upload fails when handler returns error."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_file.return_value = {
            "success": False,
            "error": "Invalid PDF structure",
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            pdf_content = b"%PDF-1.4 test content"
            response = await client.post(
                "/api/v1/upload",
                files={"file": ("test.pdf", pdf_content, "application/pdf")},
            )

            assert response.status_code == 400
            assert "Invalid PDF structure" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_from_url_success(self, client):
        """Test successful upload from URL."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_url.return_value = {
            "success": True,
            "s3_key": "documents/doc-123/abc123.pdf",
            "content_hash": "abc123def456",
            "size_bytes": 50000,
            "page_count": 25,
            "source_url": "https://example.com/paper.pdf",
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.post(
                "/api/v1/upload/from-url",
                data={"url": "https://example.com/paper.pdf"},
            )

            assert response.status_code == 200
            data = response.json()
            assert "document_id" in data
            assert data["s3_key"] == "documents/doc-123/abc123.pdf"
            assert data["content_hash"] == "abc123def456"
            assert data["source_url"] == "https://example.com/paper.pdf"
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_from_url_with_document_id(self, client):
        """Test URL upload with provided document ID."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_url.return_value = {
            "success": True,
            "s3_key": "documents/custom-id/abc123.pdf",
            "content_hash": "abc123",
            "size_bytes": 1000,
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.post(
                "/api/v1/upload/from-url",
                data={
                    "url": "https://example.com/paper.pdf",
                    "document_id": "custom-id",
                },
            )

            assert response.status_code == 200
            data = response.json()
            assert data["document_id"] == "custom-id"
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_upload_from_url_failure(self, client):
        """Test URL upload fails when download fails."""
        mock_handler = AsyncMock()
        mock_handler.upload_from_url.return_value = {
            "success": False,
            "error": "Download failed: HTTP 404",
        }

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.post(
                "/api/v1/upload/from-url",
                data={"url": "https://example.com/nonexistent.pdf"},
            )

            assert response.status_code == 400
            assert "Download failed" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_check_existing_not_found(self, client):
        """Test checking for non-existent file."""
        mock_handler = AsyncMock()
        mock_handler.check_existing.return_value = None

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/check-existing",
                params={"content_hash": "abc123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["exists"] is False
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_check_existing_found(self, client):
        """Test checking for existing file."""
        mock_handler = AsyncMock()
        mock_handler.check_existing.return_value = "documents/doc-123/abc123.pdf"

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/check-existing",
                params={"content_hash": "abc123"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["exists"] is True
            assert data["s3_key"] == "documents/doc-123/abc123.pdf"
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_get_download_url_success(self, client):
        """Test successful download URL generation."""
        mock_handler = AsyncMock()
        mock_handler.get_download_url.return_value = "https://s3.example.com/presigned-url"

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/download-url",
                params={"s3_key": "documents/doc-123/abc123.pdf"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["download_url"] == "https://s3.example.com/presigned-url"
            assert data["expires_in"] == 3600
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_get_download_url_custom_expiry(self, client):
        """Test download URL with custom expiration."""
        mock_handler = AsyncMock()
        mock_handler.get_download_url.return_value = "https://s3.example.com/presigned-url"

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/download-url",
                params={"s3_key": "documents/doc-123/abc123.pdf", "expires_in": 7200},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["expires_in"] == 7200
            mock_handler.get_download_url.assert_called_with(
                "documents/doc-123/abc123.pdf", expires_in=7200
            )
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_get_download_url_not_found(self, client):
        """Test download URL fails when PDF not found."""
        mock_handler = AsyncMock()
        mock_handler.get_download_url.return_value = None

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.get(
                "/api/v1/upload/download-url",
                params={"s3_key": "documents/nonexistent/file.pdf"},
            )

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_delete_pdf_success(self, client):
        """Test successful PDF deletion."""
        mock_handler = AsyncMock()
        mock_handler.delete_pdf.return_value = True

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.delete(
                "/api/v1/upload/doc-123",
                params={"s3_key": "documents/doc-123/abc123.pdf"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["deleted"] is True
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_delete_pdf_key_mismatch(self, client):
        """Test delete fails when s3_key doesn't match document ID."""
        mock_handler = AsyncMock()

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.delete(
                "/api/v1/upload/doc-123",
                params={"s3_key": "documents/different-doc/abc123.pdf"},
            )

            assert response.status_code == 403
            assert "does not match" in response.json()["detail"]
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)

    @pytest.mark.asyncio
    async def test_delete_pdf_failure(self, client):
        """Test delete fails when handler returns False."""
        mock_handler = AsyncMock()
        mock_handler.delete_pdf.return_value = False

        app.dependency_overrides[deps.get_upload_handler] = lambda: mock_handler

        try:
            response = await client.delete(
                "/api/v1/upload/doc-123",
                params={"s3_key": "documents/doc-123/abc123.pdf"},
            )

            assert response.status_code == 500
            assert "failed" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(deps.get_upload_handler, None)


class TestImportEndpoints:
    """Tests for import endpoints."""

    @pytest.fixture
    def mock_import_response(self):
        """Create mock import response."""
        from services.ingestion.app.core.schemas import ImportResponse, ImportStatus

        return ImportResponse(
            job_id="job-123",
            status=ImportStatus.COMPLETED,
            document_id="doc-456",
            paper=None,
            error=None,
        )

    @pytest.fixture
    def mock_import_record(self):
        """Create mock import record."""
        from services.ingestion.app.core.schemas import ImportRecord

        return ImportRecord(
            document_id=None,
            source="crossref",
            external_id="10.1234/test",
            doi="10.1234/test",
            title="Test Paper",
            authors=[{"given_name": "John", "family_name": "Smith"}],
            year=2024,
            journal="Test Journal",
        )

    @pytest.mark.asyncio
    async def test_import_requires_identifier(self, client):
        """Test import fails without identifier."""
        mock_manager = AsyncMock()

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={},
            )

            assert response.status_code == 400
            assert "identifier required" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_with_doi(self, client, mock_import_response):
        """Test import with DOI identifier."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={"doi": "10.1234/test.paper"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["job_id"] == "job-123"
            assert data["status"] == "completed"
            assert data["document_id"] == "doc-456"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_with_arxiv_id(self, client, mock_import_response):
        """Test import with arXiv identifier."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={"arxiv_id": "2401.12345"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_with_bibcode(self, client, mock_import_response):
        """Test import with ADS bibcode."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={"bibcode": "2024SoPh..299....1S"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_with_url(self, client, mock_import_response):
        """Test import with URL."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={"url": "https://example.com/paper"},
            )

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_with_download_pdf_false(self, client, mock_import_response):
        """Test import with download_pdf disabled."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import",
                json={"doi": "10.1234/test", "download_pdf": False},
            )

            assert response.status_code == 200
            # Verify the manager was called with download_pdf=False
            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.download_pdf is False
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_batch_import_success(self, client, mock_import_response):
        """Test batch import with multiple papers."""
        mock_manager = AsyncMock()
        mock_manager.batch_import.return_value = [mock_import_response, mock_import_response]

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import/batch",
                json=[
                    {
                        "source": "crossref",
                        "external_id": "10.1234/test1",
                        "title": "Paper 1",
                        "authors": [],
                    },
                    {
                        "source": "crossref",
                        "external_id": "10.1234/test2",
                        "title": "Paper 2",
                        "authors": [],
                    },
                ],
            )

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_batch_import_with_download_pdf_false(self, client, mock_import_response):
        """Test batch import with download_pdf disabled."""
        mock_manager = AsyncMock()
        mock_manager.batch_import.return_value = [mock_import_response]

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import/batch",
                params={"download_pdf": False},
                json=[
                    {
                        "source": "crossref",
                        "external_id": "10.1234/test1",
                        "title": "Paper 1",
                        "authors": [],
                    },
                ],
            )

            assert response.status_code == 200
            mock_manager.batch_import.assert_called_once()
            _, kwargs = mock_manager.batch_import.call_args
            assert kwargs["download_pdf"] is False
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_get_import_success(self, client, mock_import_record):
        """Test get import record by ID."""
        mock_manager = AsyncMock()
        mock_manager.get_import_record.return_value = mock_import_record

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/import/doc-123")

            assert response.status_code == 200
            data = response.json()
            assert data["source"] == "crossref"
            assert data["external_id"] == "10.1234/test"
            assert data["title"] == "Test Paper"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_get_import_not_found(self, client):
        """Test get import record not found."""
        mock_manager = AsyncMock()
        mock_manager.get_import_record.return_value = None

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/import/nonexistent-id")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_list_imports_success(self, client, mock_import_record):
        """Test list import records."""
        mock_manager = AsyncMock()
        mock_manager.list_imports.return_value = [mock_import_record, mock_import_record]

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/import")

            assert response.status_code == 200
            data = response.json()
            assert len(data) == 2
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_list_imports_with_filters(self, client, mock_import_record):
        """Test list imports with source and status filters."""
        mock_manager = AsyncMock()
        mock_manager.list_imports.return_value = [mock_import_record]

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.get(
                "/api/v1/import",
                params={"source": "crossref", "status": "completed", "limit": 10, "offset": 5},
            )

            assert response.status_code == 200
            mock_manager.list_imports.assert_called_once_with(
                source="crossref",
                status="completed",
                limit=10,
                offset=5,
            )
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_list_imports_empty(self, client):
        """Test list imports when empty."""
        mock_manager = AsyncMock()
        mock_manager.list_imports.return_value = []

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.get("/api/v1/import")

            assert response.status_code == 200
            assert response.json() == []
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_doi(self, client, mock_import_response):
        """Test convenience endpoint for DOI import."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/import/doi/10.1234/test.paper")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"

            # Verify import_paper was called with correct DOI
            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.doi == "10.1234/test.paper"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_doi_with_download_pdf_false(self, client, mock_import_response):
        """Test DOI import with download_pdf disabled."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import/doi/10.1234/test",
                params={"download_pdf": False},
            )

            assert response.status_code == 200
            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.download_pdf is False
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_arxiv(self, client, mock_import_response):
        """Test convenience endpoint for arXiv import."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/import/arxiv/2401.12345")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"

            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.arxiv_id == "2401.12345"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_arxiv_with_download_pdf_false(self, client, mock_import_response):
        """Test arXiv import with download_pdf disabled."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import/arxiv/2401.12345",
                params={"download_pdf": False},
            )

            assert response.status_code == 200
            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.download_pdf is False
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_bibcode(self, client, mock_import_response):
        """Test convenience endpoint for ADS bibcode import."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post("/api/v1/import/bibcode/2024SoPh..299....1S")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "completed"

            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.bibcode == "2024SoPh..299....1S"
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)

    @pytest.mark.asyncio
    async def test_import_by_bibcode_with_download_pdf_false(self, client, mock_import_response):
        """Test bibcode import with download_pdf disabled."""
        mock_manager = AsyncMock()
        mock_manager.import_paper.return_value = mock_import_response

        app.dependency_overrides[deps.get_import_manager] = lambda: mock_manager

        try:
            response = await client.post(
                "/api/v1/import/bibcode/2024SoPh..299....1S",
                params={"download_pdf": False},
            )

            assert response.status_code == 200
            call_args = mock_manager.import_paper.call_args[0][0]
            assert call_args.download_pdf is False
        finally:
            app.dependency_overrides.pop(deps.get_import_manager, None)
