"""Tests for ImportManager."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ingestion.app.core.models import ImportRecordModel
from services.ingestion.app.core.schemas import (
    ImportRecord,
    ImportRequest,
    ImportResponse,
    ImportStatus,
    IngestionJob,
    JobStatus,
    JobType,
    SearchResult,
)
from services.ingestion.app.services.import_manager import ImportManager
from shared.schemas.author import AuthorSchema


class TestImportManagerInit:
    """Tests for ImportManager initialization."""

    def test_init_with_all_dependencies(self):
        """Test initialization with all dependencies."""
        mock_db = MagicMock()
        mock_search = MagicMock()
        mock_upload = MagicMock()
        mock_sqs = MagicMock()

        manager = ImportManager(
            db=mock_db,
            search_orchestrator=mock_search,
            upload_handler=mock_upload,
            sqs_client=mock_sqs,
        )

        assert manager.db is mock_db
        assert manager.search is mock_search
        assert manager.upload_handler is mock_upload
        assert manager.sqs_client is mock_sqs

    def test_init_creates_job_manager(self):
        """Test that init creates a JobManager."""
        mock_db = MagicMock()

        manager = ImportManager(db=mock_db)

        assert manager.job_manager is not None

    @patch("services.ingestion.app.services.import_manager.SearchOrchestrator")
    @patch("services.ingestion.app.services.import_manager.UploadHandler")
    def test_init_creates_defaults(self, mock_upload_class, mock_search_class):
        """Test that init creates default dependencies."""
        mock_db = MagicMock()

        manager = ImportManager(db=mock_db)

        mock_search_class.assert_called_once()
        mock_upload_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_closes_search(self):
        """Test that close() closes search orchestrator."""
        mock_db = MagicMock()
        mock_search = MagicMock()
        mock_search.close = AsyncMock()

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)

        await manager.close()

        mock_search.close.assert_called_once()


class TestImportPaper:
    """Tests for import_paper method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test.2024",
            title="Test Paper Title",
            authors=[
                AuthorSchema(given_name="John", family_name="Doe"),
            ],
            year=2024,
            doi="10.1234/test.2024",
            abstract="Test abstract",
            journal="Test Journal",
            pdf_url="https://example.com/paper.pdf",
        )

    @pytest.fixture
    def mock_job(self):
        """Create mock IngestionJob."""
        return IngestionJob(
            job_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            job_type=JobType.IMPORT.value,
            status=JobStatus.PENDING.value,
        )

    @pytest.mark.asyncio
    async def test_import_paper_by_doi(self, mock_db, sample_paper, mock_job):
        """Test importing paper by DOI."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=sample_paper)

        mock_upload = MagicMock()
        mock_upload.upload_from_url = AsyncMock(return_value={
            "success": True,
            "s3_key": "documents/123/original.pdf",
            "content_hash": "abc123",
        })

        manager = ImportManager(
            db=mock_db,
            search_orchestrator=mock_search,
            upload_handler=mock_upload,
        )

        # Mock job manager
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()

        # Mock _check_existing_import
        manager._check_existing_import = AsyncMock(return_value=None)

        # Mock _register_document
        manager._register_document = AsyncMock(return_value={"success": True})

        request = ImportRequest(doi="10.1234/test.2024", download_pdf=True)

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.IMPORTED
        assert response.paper is not None
        mock_search.get_paper_by_doi.assert_called_once_with("10.1234/test.2024")

    @pytest.mark.asyncio
    async def test_import_paper_by_arxiv(self, mock_db, sample_paper, mock_job):
        """Test importing paper by arXiv ID."""
        sample_paper.source = "arxiv"

        mock_search = MagicMock()
        mock_search.get_paper_by_arxiv = AsyncMock(return_value=sample_paper)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()
        manager._check_existing_import = AsyncMock(return_value=None)
        manager._register_document = AsyncMock(return_value={"success": True})

        request = ImportRequest(arxiv_id="2401.12345", download_pdf=False)

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.IMPORTED
        mock_search.get_paper_by_arxiv.assert_called_once()

    @pytest.mark.asyncio
    async def test_import_paper_not_found(self, mock_db, mock_job):
        """Test import when paper not found."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=None)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()

        request = ImportRequest(doi="10.1234/nonexistent")

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.NOT_FOUND
        assert "not found" in response.error.lower()

    @pytest.mark.asyncio
    async def test_import_paper_duplicate(self, mock_db, sample_paper, mock_job):
        """Test import when paper is duplicate."""
        existing_record = ImportRecord(
            document_id=uuid.uuid4(),
            source="crossref",
            external_id="10.1234/test.2024",
            doi="10.1234/test.2024",
            title="Test Paper",
            status=ImportStatus.IMPORTED.value,
        )

        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=sample_paper)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()
        manager._check_existing_import = AsyncMock(return_value=existing_record)

        request = ImportRequest(doi="10.1234/test.2024")

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.DUPLICATE
        assert response.document_id == str(existing_record.document_id)

    @pytest.mark.asyncio
    async def test_import_paper_registration_fails(self, mock_db, sample_paper, mock_job):
        """Test import when registry registration fails."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=sample_paper)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()
        manager._check_existing_import = AsyncMock(return_value=None)
        manager._register_document = AsyncMock(return_value={
            "success": False,
            "error": "Registry unavailable",
        })

        request = ImportRequest(doi="10.1234/test.2024", download_pdf=False)

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.FAILED
        assert "Registry unavailable" in response.error

    @pytest.mark.asyncio
    async def test_import_paper_exception_handling(self, mock_db, mock_job):
        """Test import handles exceptions gracefully."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(side_effect=Exception("Network error"))

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()

        request = ImportRequest(doi="10.1234/test.2024")

        response = await manager.import_paper(request)

        assert response.status == ImportStatus.FAILED
        assert "Network error" in response.error

    @pytest.mark.asyncio
    async def test_import_paper_determines_source_correctly(self, mock_db, mock_job):
        """Test that source is determined correctly from identifiers."""
        manager = ImportManager(db=mock_db)
        manager.job_manager.create_job = AsyncMock(return_value=mock_job)
        manager.job_manager.update_status = AsyncMock()
        manager._fetch_paper_metadata = AsyncMock(return_value=None)

        # Test DOI -> crossref
        await manager.import_paper(ImportRequest(doi="10.1234/test"))
        call_kwargs = manager.job_manager.create_job.call_args.kwargs
        assert call_kwargs["source"] == "crossref"

        # Test arXiv
        await manager.import_paper(ImportRequest(arxiv_id="2401.12345"))
        call_kwargs = manager.job_manager.create_job.call_args.kwargs
        assert call_kwargs["source"] == "arxiv"

        # Test bibcode -> scixplorer
        await manager.import_paper(ImportRequest(bibcode="2024ApJ...123..456A"))
        call_kwargs = manager.job_manager.create_job.call_args.kwargs
        assert call_kwargs["source"] == "scixplorer"

        # Test URL
        await manager.import_paper(ImportRequest(url="https://example.com/paper"))
        call_kwargs = manager.job_manager.create_job.call_args.kwargs
        assert call_kwargs["source"] == "url"


class TestFetchPaperMetadata:
    """Tests for _fetch_paper_metadata method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        return MagicMock()

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            authors=[],
        )

    @pytest.mark.asyncio
    async def test_fetch_by_doi_first(self, mock_db, sample_paper):
        """Test that DOI is tried first."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=sample_paper)
        mock_search.get_paper_by_arxiv = AsyncMock(return_value=None)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)

        request = ImportRequest(doi="10.1234/test", arxiv_id="2401.12345")
        result = await manager._fetch_paper_metadata(request)

        assert result == sample_paper
        mock_search.get_paper_by_doi.assert_called_once()
        mock_search.get_paper_by_arxiv.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_falls_back_to_arxiv(self, mock_db, sample_paper):
        """Test fallback to arXiv when DOI not found."""
        mock_search = MagicMock()
        mock_search.get_paper_by_doi = AsyncMock(return_value=None)
        mock_search.get_paper_by_arxiv = AsyncMock(return_value=sample_paper)

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)

        request = ImportRequest(doi="10.1234/notfound", arxiv_id="2401.12345")
        result = await manager._fetch_paper_metadata(request)

        assert result == sample_paper
        mock_search.get_paper_by_doi.assert_called_once()
        mock_search.get_paper_by_arxiv.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_by_bibcode(self, mock_db, sample_paper):
        """Test fetching by bibcode."""
        mock_connector = MagicMock()
        mock_connector.get_paper = AsyncMock(return_value=sample_paper)

        mock_search = MagicMock()
        mock_search.connectors = {"scixplorer": mock_connector}

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)

        request = ImportRequest(bibcode="2024ApJ...123..456A")
        result = await manager._fetch_paper_metadata(request)

        assert result == sample_paper
        mock_connector.get_paper.assert_called_once_with("2024ApJ...123..456A")

    @pytest.mark.asyncio
    async def test_fetch_returns_none_for_url_only(self, mock_db):
        """Test that URL-only request returns None (not yet supported)."""
        mock_search = MagicMock()

        manager = ImportManager(db=mock_db, search_orchestrator=mock_search)

        request = ImportRequest(url="https://example.com/paper.pdf")
        result = await manager._fetch_paper_metadata(request)

        assert result is None


class TestCheckExistingImport:
    """Tests for _check_existing_import method."""

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            doi="10.1234/test",
            authors=[],
        )

    @pytest.mark.asyncio
    async def test_check_existing_by_doi(self, sample_paper):
        """Test checking existing import by DOI."""
        existing_record = MagicMock()
        existing_record.document_id = uuid.uuid4()
        existing_record.source = "crossref"
        existing_record.external_id = "10.1234/test"
        existing_record.doi = "10.1234/test"
        existing_record.title = "Test Paper"
        existing_record.authors = []
        existing_record.year = 2024
        existing_record.journal = None
        existing_record.abstract = None
        existing_record.pdf_url = None
        existing_record.s3_key = None
        existing_record.content_hash = None
        existing_record.source_metadata = {}
        existing_record.status = "imported"
        existing_record.created_at = datetime.now(timezone.utc)
        existing_record.updated_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_record

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        result = await manager._check_existing_import(sample_paper)

        assert result is not None
        assert result.doi == "10.1234/test"

    @pytest.mark.asyncio
    async def test_check_existing_by_external_id(self):
        """Test checking existing import by external ID when DOI not found."""
        paper = SearchResult(
            source="arxiv",
            external_id="2401.12345",
            title="Test Paper",
            authors=[],
        )

        existing_record = MagicMock()
        existing_record.document_id = uuid.uuid4()
        existing_record.source = "arxiv"
        existing_record.external_id = "2401.12345"
        existing_record.doi = None
        existing_record.title = "Test Paper"
        existing_record.authors = []
        existing_record.year = 2024
        existing_record.journal = None
        existing_record.abstract = None
        existing_record.pdf_url = None
        existing_record.s3_key = None
        existing_record.content_hash = None
        existing_record.source_metadata = {}
        existing_record.status = "imported"
        existing_record.created_at = datetime.now(timezone.utc)
        existing_record.updated_at = None

        # First query (DOI) returns None, second query (external_id) returns record
        mock_result_none = MagicMock()
        mock_result_none.scalar_one_or_none.return_value = None

        mock_result_found = MagicMock()
        mock_result_found.scalar_one_or_none.return_value = existing_record

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(side_effect=[mock_result_found])

        manager = ImportManager(db=mock_db)

        result = await manager._check_existing_import(paper)

        assert result is not None
        assert result.external_id == "2401.12345"

    @pytest.mark.asyncio
    async def test_check_existing_returns_none(self):
        """Test returns None when no existing import found."""
        paper = SearchResult(
            source="crossref",
            external_id="new-paper",
            title="New Paper",
            doi="10.1234/new",
            authors=[],
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        result = await manager._check_existing_import(paper)

        assert result is None


class TestRegisterDocument:
    """Tests for _register_document method."""

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            doi="10.1234/test",
            authors=[AuthorSchema(given_name="John", family_name="Doe")],
            year=2024,
            journal="Test Journal",
        )

    @pytest.mark.asyncio
    @patch("services.ingestion.app.services.import_manager.settings")
    @patch("httpx.AsyncClient")
    async def test_register_document_success(
        self, mock_client_class, mock_settings, sample_paper
    ):
        """Test successful document registration."""
        mock_settings.document_registry_url = "http://registry:8000"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"document_id": "123"}

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        result = await manager._register_document(
            document_id="doc-123",
            paper=sample_paper,
            pdf_result={"success": True, "s3_key": "docs/pdf", "content_hash": "abc"},
        )

        assert result["success"] is True
        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.ingestion.app.services.import_manager.settings")
    async def test_register_document_no_registry_url(self, mock_settings, sample_paper):
        """Test registration when registry URL not configured."""
        mock_settings.document_registry_url = None

        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        result = await manager._register_document(
            document_id="doc-123",
            paper=sample_paper,
            pdf_result=None,
        )

        assert result["success"] is True
        assert "not configured" in result["message"]

    @pytest.mark.asyncio
    @patch("services.ingestion.app.services.import_manager.settings")
    async def test_register_document_http_error(self, mock_settings, sample_paper):
        """Test registration when HTTP error occurs."""
        mock_settings.document_registry_url = "http://registry:8000"

        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        doc_id = str(uuid.uuid4())

        # Patch httpx module used in import_manager
        with patch("services.ingestion.app.services.import_manager.httpx") as mock_httpx:
            # Create a context manager mock that raises on post
            mock_client = MagicMock()
            mock_client.post = AsyncMock(side_effect=Exception("Connection refused"))

            # Make AsyncClient return an async context manager
            mock_context = MagicMock()
            mock_context.__aenter__ = AsyncMock(return_value=mock_client)
            mock_context.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.AsyncClient.return_value = mock_context

            result = await manager._register_document(
                document_id=doc_id,
                paper=sample_paper,
                pdf_result=None,
            )

        assert result["success"] is False
        assert "Connection refused" in result["error"]


class TestPublishImportEvent:
    """Tests for _publish_import_event method."""

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            doi="10.1234/test",
            authors=[],
        )

    @pytest.mark.asyncio
    @patch("services.ingestion.app.services.import_manager.settings")
    async def test_publish_event_success(self, mock_settings, sample_paper):
        """Test successful event publishing."""
        mock_settings.sqs_document_events_url = "http://sqs/events"

        mock_sqs = MagicMock()
        mock_sqs.send_message = AsyncMock()

        mock_db = MagicMock()
        manager = ImportManager(db=mock_db, sqs_client=mock_sqs)

        await manager._publish_import_event("doc-123", sample_paper)

        mock_sqs.send_message.assert_called_once()
        call_kwargs = mock_sqs.send_message.call_args.kwargs
        assert call_kwargs["message"]["event_type"] == "DocumentImported"
        assert call_kwargs["message"]["document_id"] == "doc-123"

    @pytest.mark.asyncio
    async def test_publish_event_no_sqs_client(self, sample_paper):
        """Test no error when SQS client not configured."""
        mock_db = MagicMock()
        manager = ImportManager(db=mock_db, sqs_client=None)

        # Should not raise
        await manager._publish_import_event("doc-123", sample_paper)

    @pytest.mark.asyncio
    @patch("services.ingestion.app.services.import_manager.settings")
    async def test_publish_event_handles_error(self, mock_settings, sample_paper):
        """Test error handling in event publishing."""
        mock_settings.sqs_document_events_url = "http://sqs/events"

        mock_sqs = MagicMock()
        mock_sqs.send_message = AsyncMock(side_effect=Exception("SQS error"))

        mock_db = MagicMock()
        manager = ImportManager(db=mock_db, sqs_client=mock_sqs)

        # Should not raise
        await manager._publish_import_event("doc-123", sample_paper)


class TestGetImportRecord:
    """Tests for get_import_record method."""

    @pytest.mark.asyncio
    async def test_get_import_record_found(self):
        """Test getting existing import record."""
        record = MagicMock()
        record.document_id = uuid.uuid4()
        record.source = "crossref"
        record.external_id = "10.1234/test"
        record.doi = "10.1234/test"
        record.title = "Test Paper"
        record.authors = []
        record.year = 2024
        record.journal = "Test Journal"
        record.abstract = None
        record.pdf_url = None
        record.s3_key = None
        record.content_hash = None
        record.source_metadata = {}
        record.status = "imported"
        record.created_at = datetime.now(timezone.utc)
        record.updated_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        result = await manager.get_import_record(str(record.document_id))

        assert result is not None
        assert result.doi == "10.1234/test"

    @pytest.mark.asyncio
    async def test_get_import_record_not_found(self):
        """Test getting non-existent import record."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        result = await manager.get_import_record("nonexistent-id")

        assert result is None


class TestListImports:
    """Tests for list_imports method."""

    @pytest.mark.asyncio
    async def test_list_imports_all(self):
        """Test listing all imports."""
        records = []
        for i in range(3):
            record = MagicMock()
            record.document_id = uuid.uuid4()
            record.source = "crossref"
            record.external_id = f"10.1234/test{i}"
            record.doi = f"10.1234/test{i}"
            record.title = f"Test Paper {i}"
            record.authors = []
            record.year = 2024
            record.journal = None
            record.abstract = None
            record.pdf_url = None
            record.s3_key = None
            record.content_hash = None
            record.source_metadata = {}
            record.status = "imported"
            record.created_at = datetime.now(timezone.utc)
            record.updated_at = None
            records.append(record)

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = records

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        result = await manager.list_imports()

        assert len(result) == 3

    @pytest.mark.asyncio
    async def test_list_imports_with_filters(self):
        """Test listing imports with filters."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []

        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        manager = ImportManager(db=mock_db)

        await manager.list_imports(
            source="arxiv",
            status=ImportStatus.IMPORTED,
            limit=10,
            offset=5,
        )

        # Verify execute was called (filter logic is in query building)
        mock_db.execute.assert_called_once()


class TestBatchImport:
    """Tests for batch_import method."""

    @pytest.fixture
    def sample_papers(self):
        """Create sample papers for batch import."""
        return [
            SearchResult(
                source="crossref",
                external_id="10.1234/test1",
                title="Paper 1",
                doi="10.1234/test1",
                authors=[],
            ),
            SearchResult(
                source="arxiv",
                external_id="2401.12345",
                title="Paper 2",
                authors=[],
                source_metadata={"arxiv_id": "2401.12345"},
            ),
        ]

    @pytest.mark.asyncio
    async def test_batch_import_processes_all_papers(self, sample_papers):
        """Test that batch import processes all papers."""
        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        # Mock import_paper to return success
        manager.import_paper = AsyncMock(
            side_effect=[
                ImportResponse(job_id="job1", status=ImportStatus.IMPORTED),
                ImportResponse(job_id="job2", status=ImportStatus.IMPORTED),
            ]
        )

        results = await manager.batch_import(sample_papers, download_pdf=True)

        assert len(results) == 2
        assert manager.import_paper.call_count == 2

    @pytest.mark.asyncio
    async def test_batch_import_continues_on_failure(self, sample_papers):
        """Test that batch import continues when one fails."""
        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        manager.import_paper = AsyncMock(
            side_effect=[
                ImportResponse(job_id="job1", status=ImportStatus.FAILED, error="Failed"),
                ImportResponse(job_id="job2", status=ImportStatus.IMPORTED),
            ]
        )

        results = await manager.batch_import(sample_papers)

        assert len(results) == 2
        assert results[0].status == ImportStatus.FAILED
        assert results[1].status == ImportStatus.IMPORTED


class TestCreateImportRecord:
    """Tests for _create_import_record method."""

    @pytest.fixture
    def sample_paper(self):
        """Create sample SearchResult."""
        return SearchResult(
            source="crossref",
            external_id="10.1234/test",
            title="Test Paper",
            doi="10.1234/test",
            authors=[AuthorSchema(given_name="John", family_name="Doe")],
            year=2024,
            journal="Test Journal",
            abstract="Test abstract",
            pdf_url="https://example.com/paper.pdf",
        )

    @pytest.mark.asyncio
    async def test_create_import_record_with_pdf(self, sample_paper):
        """Test creating import record with PDF."""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Mock refresh to set attributes on the record
        async def mock_refresh(record):
            record.created_at = datetime.now(timezone.utc)
            record.updated_at = None

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        manager = ImportManager(db=mock_db)

        doc_id = str(uuid.uuid4())
        pdf_result = {
            "success": True,
            "s3_key": "documents/123/paper.pdf",
            "content_hash": "abc123hash",
        }

        result = await manager._create_import_record(
            document_id=doc_id,
            paper=sample_paper,
            pdf_result=pdf_result,
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

        # Check the record was created with correct values
        added_record = mock_db.add.call_args[0][0]
        assert added_record.s3_key == "documents/123/paper.pdf"
        assert added_record.content_hash == "abc123hash"

    @pytest.mark.asyncio
    async def test_create_import_record_without_pdf(self, sample_paper):
        """Test creating import record without PDF."""
        mock_db = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = AsyncMock()

        # Mock refresh to set attributes on the record
        async def mock_refresh(record):
            record.created_at = datetime.now(timezone.utc)
            record.updated_at = None

        mock_db.refresh = AsyncMock(side_effect=mock_refresh)

        manager = ImportManager(db=mock_db)

        doc_id = str(uuid.uuid4())
        result = await manager._create_import_record(
            document_id=doc_id,
            paper=sample_paper,
            pdf_result=None,
        )

        mock_db.add.assert_called_once()
        # Check that the record was added without s3_key
        added_record = mock_db.add.call_args[0][0]
        assert added_record.s3_key is None
        assert added_record.content_hash is None


class TestRecordToSchema:
    """Tests for _record_to_schema method."""

    def test_record_to_schema_conversion(self):
        """Test converting model to schema."""
        mock_db = MagicMock()
        manager = ImportManager(db=mock_db)

        model = MagicMock()
        model.document_id = uuid.uuid4()
        model.source = "crossref"
        model.external_id = "10.1234/test"
        model.doi = "10.1234/test"
        model.title = "Test Paper"
        model.authors = [{"given_name": "John", "family_name": "Doe"}]
        model.year = 2024
        model.journal = "Test Journal"
        model.abstract = "Test abstract"
        model.pdf_url = "https://example.com/paper.pdf"
        model.s3_key = "documents/123/paper.pdf"
        model.content_hash = "abc123"
        model.source_metadata = {"key": "value"}
        model.status = "imported"
        model.created_at = datetime.now(timezone.utc)
        model.updated_at = datetime.now(timezone.utc)

        result = manager._record_to_schema(model)

        assert isinstance(result, ImportRecord)
        assert result.source == "crossref"
        assert result.doi == "10.1234/test"
        assert result.title == "Test Paper"
        assert result.year == 2024
        assert result.s3_key == "documents/123/paper.pdf"
