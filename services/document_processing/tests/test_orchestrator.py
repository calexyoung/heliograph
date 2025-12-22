"""Tests for pipeline orchestrator."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.document_processing.app.core.models import ChunkModel, ProcessingJobModel
from services.document_processing.app.core.schemas import (
    Chunk,
    ChunkWithEmbedding,
    DocumentIndexedEvent,
    DocumentRegisteredEvent,
    ExtractedText,
    ParsedSection,
    PipelineStage,
    ProcessingResult,
    ProcessingStatus,
    SectionType,
    StorageConfig,
)
from services.document_processing.app.parsers.factory import ParserFactory
from services.document_processing.app.pipeline.orchestrator import PipelineOrchestrator


class TestOrchestratorParserFactory:
    """Tests for orchestrator's ParserFactory integration."""

    def test_orchestrator_imports_parser_factory(self):
        """Test that orchestrator imports ParserFactory."""
        # This verifies the import doesn't fail
        from services.document_processing.app.pipeline.orchestrator import PipelineOrchestrator
        assert PipelineOrchestrator is not None

    def test_parser_factory_initialization(self):
        """Test ParserFactory is initialized with correct settings."""
        with patch("services.document_processing.app.parsers.factory.settings") as mock_settings:
            mock_settings.DOCLING_ENABLED = True

            factory = ParserFactory(docling_enabled=True, prefer_grobid_for_scientific=True)

            assert factory.docling_enabled is True
            assert factory.prefer_grobid_for_scientific is True

    @pytest.mark.asyncio
    async def test_parser_factory_routes_pdf_to_docling(self):
        """Test PDF routing to Docling when enabled."""
        from services.document_processing.app.core.schemas import ExtractedText
        from services.document_processing.app.parsers.docling_parser import FileType

        factory = ParserFactory(docling_enabled=True)

        mock_result = ExtractedText(
            full_text="Test content",
            sections=[],
            references=[],
            page_count=1,
            metadata={"parser": "docling"},
        )

        with patch.object(factory, "get_docling_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.parse_pdf = AsyncMock(return_value=mock_result)
            mock_get_parser.return_value = mock_parser

            result = await factory.parse(b"%PDF-1.4 content", filename="document.pdf")

            assert result.metadata["parser"] == "docling"

    @pytest.mark.asyncio
    async def test_parser_factory_routes_docx_to_docling(self):
        """Test DOCX routing requires Docling."""
        from services.document_processing.app.core.schemas import ExtractedText
        from services.document_processing.app.parsers.docling_parser import FileType

        factory = ParserFactory(docling_enabled=True)

        mock_result = ExtractedText(
            full_text="DOCX content",
            sections=[],
            references=[],
            page_count=1,
            metadata={"parser": "docling", "file_type": "docx"},
        )

        with patch.object(factory, "get_docling_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.parse = AsyncMock(return_value=mock_result)
            mock_get_parser.return_value = mock_parser

            result = await factory.parse(b"PK\x03\x04 docx content", filename="document.docx")

            assert result.metadata["parser"] == "docling"

    @pytest.mark.asyncio
    async def test_parser_factory_rejects_docx_without_docling(self):
        """Test DOCX is rejected when Docling is disabled."""
        factory = ParserFactory(docling_enabled=False)

        with pytest.raises(ValueError, match="Cannot parse docx"):
            await factory.parse(b"content", filename="document.docx")

    @pytest.mark.asyncio
    async def test_parser_factory_falls_back_to_grobid(self):
        """Test PDF falls back to GROBID when Docling disabled."""
        from services.document_processing.app.core.schemas import ExtractedText

        factory = ParserFactory(docling_enabled=False)

        mock_result = ExtractedText(
            full_text="GROBID content",
            sections=[],
            references=[],
            page_count=1,
            metadata={"parser": "grobid"},
        )

        with patch.object(factory, "get_grobid_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.parse_pdf = AsyncMock(return_value=mock_result)
            mock_get_parser.return_value = mock_parser

            result = await factory.parse(b"%PDF-1.4 content", filename="test.pdf")

            assert result.metadata["parser"] == "grobid"

    def test_parser_factory_supported_formats_with_docling(self):
        """Test all formats supported when Docling enabled."""
        factory = ParserFactory(docling_enabled=True)
        formats = factory.get_supported_formats()

        assert ".pdf" in formats
        assert ".docx" in formats
        assert ".pptx" in formats
        assert ".xlsx" in formats
        assert ".html" in formats
        assert ".png" in formats
        assert ".md" in formats

    def test_parser_factory_supported_formats_without_docling(self):
        """Test only PDF supported when Docling disabled."""
        factory = ParserFactory(docling_enabled=False)
        formats = factory.get_supported_formats()

        assert formats == [".pdf"]

    @pytest.mark.asyncio
    async def test_parser_factory_health_check(self):
        """Test health check returns parser status."""
        from services.document_processing.app.parsers.factory import ParserFactory

        factory = ParserFactory(docling_enabled=True)

        with patch.object(factory, "get_docling_parser") as mock_docling:
            with patch.object(factory, "get_grobid_parser") as mock_grobid:
                mock_docling_parser = MagicMock()
                mock_docling_parser.check_health = AsyncMock(return_value=True)
                mock_docling.return_value = mock_docling_parser

                mock_grobid_parser = MagicMock()
                mock_grobid_parser.check_health = AsyncMock(return_value=True)
                mock_grobid.return_value = mock_grobid_parser

                health = await factory.check_health()

                assert health["docling"] is True
                assert health["grobid"] is True

    @pytest.mark.asyncio
    async def test_parser_factory_uses_filename_for_type_detection(self):
        """Test that filename is used for file type detection."""
        from services.document_processing.app.parsers.docling_parser import detect_file_type, FileType

        # Test various filename patterns
        assert detect_file_type("documents/123/paper.pdf") == FileType.PDF
        assert detect_file_type("uploads/report.docx") == FileType.DOCX
        assert detect_file_type("slides/presentation.pptx") == FileType.PPTX
        assert detect_file_type("data/spreadsheet.xlsx") == FileType.XLSX

    @pytest.mark.asyncio
    async def test_parser_factory_extracts_from_s3_key(self):
        """Test S3 key is used for file type detection in parse call."""
        from services.document_processing.app.core.schemas import ExtractedText

        factory = ParserFactory(docling_enabled=True)

        mock_result = ExtractedText(
            full_text="Content",
            sections=[],
            references=[],
            page_count=1,
            metadata={"parser": "docling"},
        )

        # Simulate S3 key path like "documents/{uuid}/original.pdf"
        s3_key = f"documents/{uuid4()}/original.pdf"

        with patch.object(factory, "get_docling_parser") as mock_get_parser:
            mock_parser = MagicMock()
            mock_parser.parse_pdf = AsyncMock(return_value=mock_result)
            mock_get_parser.return_value = mock_parser

            result = await factory.parse(b"%PDF content", filename=s3_key)

            # Should detect PDF from S3 key
            mock_parser.parse_pdf.assert_called_once()


# ============================================================================
# PipelineOrchestrator Tests
# ============================================================================


class TestPipelineOrchestratorInit:
    """Tests for PipelineOrchestrator initialization."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    def test_init_with_all_dependencies(self, mock_db, mock_storage_client, mock_sqs_client):
        """Test initialization with all dependencies provided."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
            sqs_client=mock_sqs_client,
        )

        assert orchestrator.db is mock_db
        assert orchestrator.storage_client is mock_storage_client
        assert orchestrator.sqs_client is mock_sqs_client

    def test_init_creates_pipeline_components(self, mock_db, mock_storage_client):
        """Test that init creates pipeline components."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        assert orchestrator.parser_factory is not None
        assert orchestrator.segmenter is not None
        assert orchestrator.chunker is not None
        assert orchestrator.embedding_generator is not None
        assert orchestrator.qdrant_client is not None

    @patch("services.document_processing.app.pipeline.orchestrator.get_storage_client")
    def test_init_creates_storage_client_from_settings(self, mock_get_storage, mock_db):
        """Test that storage client is created from settings when not provided."""
        mock_client = MagicMock()
        mock_get_storage.return_value = mock_client

        orchestrator = PipelineOrchestrator(db=mock_db)

        mock_get_storage.assert_called_once()
        assert orchestrator.storage_client is mock_client


class TestPipelineOrchestratorDownload:
    """Tests for _download_pdf method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_download_pdf_success(self, mock_db, mock_storage_client):
        """Test successful PDF download."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        pdf_content = await orchestrator._download_pdf("documents/123/original.pdf")

        assert pdf_content == b"%PDF-1.4 test content"
        mock_storage_client.download_object.assert_called_once_with(
            key="documents/123/original.pdf"
        )

    @pytest.mark.asyncio
    async def test_download_pdf_propagates_error(self, mock_db, mock_storage_client):
        """Test that download errors are propagated."""
        mock_storage_client.download_object = AsyncMock(side_effect=Exception("S3 error"))

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        with pytest.raises(Exception, match="S3 error"):
            await orchestrator._download_pdf("documents/123/original.pdf")


class TestPipelineOrchestratorStoreArtifact:
    """Tests for _store_artifact method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_store_artifact_string_content(self, mock_db, mock_storage_client):
        """Test storing string artifact."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        s3_key = await orchestrator._store_artifact(
            document_id=doc_id,
            filename="extracted_text.json",
            content='{"text": "hello"}',
        )

        assert s3_key == f"documents/{doc_id}/artifacts/extracted_text.json"
        mock_storage_client.upload_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_artifact_dict_content(self, mock_db, mock_storage_client):
        """Test storing dict artifact (converts to JSON)."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        await orchestrator._store_artifact(
            document_id=doc_id,
            filename="metadata.json",
            content={"key": "value", "number": 42},
        )

        call_args = mock_storage_client.upload_bytes.call_args
        uploaded_data = call_args.kwargs.get("data") or call_args[1].get("data")
        assert b'"key": "value"' in uploaded_data
        assert b'"number": 42' in uploaded_data

    @pytest.mark.asyncio
    async def test_store_artifact_list_content(self, mock_db, mock_storage_client):
        """Test storing list artifact (converts to JSON)."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        await orchestrator._store_artifact(
            document_id=doc_id,
            filename="chunks.json",
            content=[{"id": 1}, {"id": 2}],
        )

        mock_storage_client.upload_bytes.assert_called_once()


class TestPipelineOrchestratorStoreChunks:
    """Tests for _store_chunks method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_store_chunks_adds_to_db(self, mock_db, mock_storage_client):
        """Test that chunks are added to database."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        chunks = [
            ChunkWithEmbedding(
                chunk_id=uuid4(),
                document_id=doc_id,
                sequence_number=0,
                text="Test chunk 1",
                section=SectionType.ABSTRACT,
                char_offset_start=0,
                char_offset_end=12,
                token_count=3,
                embedding=[0.1, 0.2, 0.3],
            ),
            ChunkWithEmbedding(
                chunk_id=uuid4(),
                document_id=doc_id,
                sequence_number=1,
                text="Test chunk 2",
                section=None,
                char_offset_start=13,
                char_offset_end=25,
                token_count=3,
                embedding=[0.4, 0.5, 0.6],
            ),
        ]

        await orchestrator._store_chunks(chunks)

        assert mock_db.add.call_count == 2
        mock_db.commit.assert_called_once()


class TestPipelineOrchestratorJobManagement:
    """Tests for job management methods."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_update_job_stage(self, mock_db, mock_storage_client):
        """Test updating job stage."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        job_id = uuid4()
        await orchestrator._update_job_stage(job_id, PipelineStage.PDF_PARSING)

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_stage_complete(self, mock_db, mock_storage_client):
        """Test marking a stage as complete."""
        # Setup mock result for select query
        mock_job = MagicMock()
        mock_job.stages_completed = []
        mock_job.stage_timings = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job
        mock_db.execute = AsyncMock(return_value=mock_result)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        job_id = uuid4()
        await orchestrator._mark_stage_complete(
            job_id, PipelineStage.PDF_PARSING, timing=1.5
        )

        # Should have two execute calls: select and update
        assert mock_db.execute.call_count == 2

    @pytest.mark.asyncio
    async def test_mark_stage_complete_job_not_found(self, mock_db, mock_storage_client):
        """Test marking stage complete when job not found."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        job_id = uuid4()
        await orchestrator._mark_stage_complete(
            job_id, PipelineStage.PDF_PARSING, timing=1.5
        )

        # Should only have one execute call (the select)
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_complete_job(self, mock_db, mock_storage_client):
        """Test completing a job."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        job_id = uuid4()
        await orchestrator._complete_job(
            job_id=job_id,
            chunk_count=10,
            entity_count=5,
            stage_timings={"pdf_parsing": 1.0, "chunking": 0.5},
        )

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_fail_job(self, mock_db, mock_storage_client):
        """Test failing a job."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        job_id = uuid4()
        await orchestrator._fail_job(job_id, error="Processing failed")

        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()


class TestPipelineOrchestratorDocumentState:
    """Tests for document state management."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("httpx.AsyncClient")
    async def test_update_document_state_success(
        self, mock_http_client_class, mock_settings, mock_db, mock_storage_client
    ):
        """Test successful document state update."""
        mock_settings.DOCUMENT_REGISTRY_URL = "http://registry:8000"
        mock_settings.SERVICE_NAME = "document-processing"

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_http_client_class.return_value = mock_client

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        await orchestrator._update_document_state(doc_id, "processing")

        mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    async def test_update_document_state_no_registry_url(
        self, mock_settings, mock_db, mock_storage_client
    ):
        """Test that no error occurs when registry URL not configured."""
        mock_settings.DOCUMENT_REGISTRY_URL = None

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        # Should not raise
        await orchestrator._update_document_state(doc_id, "processing")


class TestPipelineOrchestratorPublishEvent:
    """Tests for event publishing."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    async def test_publish_indexed_event(
        self, mock_settings, mock_db, mock_storage_client, mock_sqs_client
    ):
        """Test publishing DocumentIndexed event."""
        mock_settings.SQS_DOCUMENT_INDEXED_URL = "http://sqs/indexed"

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
            sqs_client=mock_sqs_client,
        )

        doc_id = uuid4()
        await orchestrator._publish_indexed_event(
            document_id=doc_id,
            chunk_count=10,
            entity_count=5,
            processing_time=2.5,
            correlation_id="test-correlation",
        )

        mock_sqs_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_indexed_event_no_sqs_client(
        self, mock_db, mock_storage_client
    ):
        """Test that no error when SQS client not configured."""
        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
            sqs_client=None,
        )

        doc_id = uuid4()
        # Should not raise
        await orchestrator._publish_indexed_event(
            document_id=doc_id,
            chunk_count=10,
            entity_count=5,
            processing_time=2.5,
            correlation_id="test-correlation",
        )


class TestPipelineOrchestratorKnowledgeExtraction:
    """Tests for knowledge extraction methods."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()
        db.execute = AsyncMock()
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("httpx.AsyncClient")
    async def test_extract_knowledge_success(
        self, mock_http_client_class, mock_settings, mock_db, mock_storage_client
    ):
        """Test successful knowledge extraction."""
        mock_settings.KNOWLEDGE_EXTRACTION_URL = "http://knowledge:8000"

        # Mock job creation response
        mock_job_response = MagicMock()
        mock_job_response.raise_for_status = MagicMock()
        mock_job_response.json.return_value = {"job_id": "test-job-123"}

        # Mock extraction response
        mock_extract_response = MagicMock()
        mock_extract_response.raise_for_status = MagicMock()
        mock_extract_response.json.return_value = {
            "entities": [{"name": "solar flare"}, {"name": "CME"}],
            "relationships": [{"source": "solar flare", "target": "CME"}],
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_job_response, mock_extract_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_http_client_class.return_value = mock_client

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        chunks = [
            Chunk(
                chunk_id=uuid4(),
                document_id=doc_id,
                sequence_number=0,
                text="Solar flares cause CMEs.",
                char_offset_start=0,
                char_offset_end=24,
                token_count=5,
            )
        ]

        entity_count = await orchestrator._extract_knowledge(
            document_id=doc_id,
            chunks=chunks,
            doc_metadata={"title": "Test"},
        )

        assert entity_count == 2

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("httpx.AsyncClient")
    async def test_extract_knowledge_service_error(
        self, mock_http_client_class, mock_settings, mock_db, mock_storage_client
    ):
        """Test knowledge extraction handles service errors gracefully."""
        mock_settings.KNOWLEDGE_EXTRACTION_URL = "http://knowledge:8000"

        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(
            side_effect=httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_response)
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_http_client_class.return_value = mock_client

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        doc_id = uuid4()
        chunks = [
            Chunk(
                chunk_id=uuid4(),
                document_id=doc_id,
                sequence_number=0,
                text="Test chunk",
                char_offset_start=0,
                char_offset_end=10,
                token_count=2,
            )
        ]

        # Should not raise, returns 0
        entity_count = await orchestrator._extract_knowledge(
            document_id=doc_id,
            chunks=chunks,
            doc_metadata={"title": "Test"},
        )

        assert entity_count == 0


class TestPipelineOrchestratorProcessDocument:
    """Tests for process_document method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        # Mock for select queries (mark_stage_complete)
        mock_job = MagicMock()
        mock_job.stages_completed = []
        mock_job.stage_timings = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job

        db.execute = AsyncMock(return_value=mock_result)
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.fixture
    def mock_sqs_client(self):
        """Create mock SQS client."""
        client = MagicMock()
        client.send_message = AsyncMock()
        return client

    @pytest.fixture
    def sample_event(self):
        """Create sample DocumentRegisteredEvent."""
        return DocumentRegisteredEvent(
            document_id=uuid4(),
            content_hash="abc123",
            doi="10.1234/test",
            title="Test Document",
            s3_key="documents/test-id/original.pdf",
            user_id=uuid4(),
            correlation_id="corr-123",
            timestamp=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def sample_extracted_text(self):
        """Create sample ExtractedText."""
        return ExtractedText(
            full_text="This is the abstract. This is the introduction.",
            sections=[
                ParsedSection(
                    section_type=SectionType.ABSTRACT,
                    text="This is the abstract.",
                    char_offset_start=0,
                    char_offset_end=21,
                ),
                ParsedSection(
                    section_type=SectionType.INTRODUCTION,
                    text="This is the introduction.",
                    char_offset_start=22,
                    char_offset_end=47,
                ),
            ],
            references=[],
            page_count=1,
            metadata={"parser": "docling"},
        )

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    async def test_process_document_success(
        self,
        mock_settings,
        mock_db,
        mock_storage_client,
        mock_sqs_client,
        sample_event,
        sample_extracted_text,
    ):
        """Test successful document processing."""
        mock_settings.S3_BUCKET = "test-bucket"
        mock_settings.DOCUMENT_REGISTRY_URL = None
        mock_settings.ENABLE_KNOWLEDGE_EXTRACTION = False
        mock_settings.SQS_DOCUMENT_INDEXED_URL = "http://sqs/indexed"

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
            sqs_client=mock_sqs_client,
        )

        # Mock parser factory
        orchestrator.parser_factory.parse = AsyncMock(return_value=sample_extracted_text)

        # Mock segmenter
        orchestrator.segmenter.segment = MagicMock(return_value=sample_extracted_text.sections)
        orchestrator.segmenter.create_structure_map = MagicMock(return_value='{"sections": []}')

        # Mock chunker
        mock_chunks = [
            Chunk(
                chunk_id=uuid4(),
                document_id=sample_event.document_id,
                sequence_number=0,
                text="This is the abstract.",
                section=SectionType.ABSTRACT,
                char_offset_start=0,
                char_offset_end=21,
                token_count=5,
            )
        ]
        orchestrator.chunker.chunk_document = MagicMock(return_value=mock_chunks)

        # Mock embedding generator
        mock_chunks_with_embeddings = [
            ChunkWithEmbedding(
                **mock_chunks[0].model_dump(),
                embedding=[0.1] * 384,
            )
        ]
        orchestrator.embedding_generator.generate_embeddings = AsyncMock(
            return_value=mock_chunks_with_embeddings
        )

        # Mock Qdrant
        orchestrator.qdrant_client.upsert_chunks = AsyncMock()

        result = await orchestrator.process_document(sample_event, "worker-1")

        assert result.success is True
        assert result.document_id == sample_event.document_id
        assert result.chunk_count == 1
        assert "download" in result.stage_timings
        assert "pdf_parsing" in result.stage_timings

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    async def test_process_document_failure(
        self,
        mock_settings,
        mock_db,
        mock_storage_client,
        sample_event,
    ):
        """Test document processing failure handling."""
        mock_settings.DOCUMENT_REGISTRY_URL = None

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        # Make parser fail
        orchestrator.parser_factory.parse = AsyncMock(
            side_effect=ValueError("Failed to parse PDF")
        )

        result = await orchestrator.process_document(sample_event, "worker-1")

        assert result.success is False
        assert "Failed to parse PDF" in result.error
        assert result.document_id == sample_event.document_id

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("services.document_processing.app.pipeline.orchestrator.get_storage_client")
    async def test_process_document_with_storage_config(
        self,
        mock_get_storage,
        mock_settings,
        mock_db,
        mock_storage_client,
        sample_extracted_text,
    ):
        """Test document processing with event-specific storage config."""
        mock_settings.S3_BUCKET = "test-bucket"
        mock_settings.DOCUMENT_REGISTRY_URL = None
        mock_settings.ENABLE_KNOWLEDGE_EXTRACTION = False
        mock_settings.LOCAL_STORAGE_PATH = "/tmp/storage"
        mock_settings.AWS_REGION = "us-east-1"
        mock_settings.S3_ENDPOINT_URL = None
        mock_settings.AWS_ACCESS_KEY_ID = None
        mock_settings.AWS_SECRET_ACCESS_KEY = None

        # Create a local storage client mock
        mock_local_storage = MagicMock()
        mock_local_storage.download_object = AsyncMock(return_value=b"%PDF-1.4 content")
        mock_local_storage.upload_bytes = AsyncMock()
        mock_get_storage.return_value = mock_local_storage

        event = DocumentRegisteredEvent(
            document_id=uuid4(),
            content_hash="abc123",
            doi="10.1234/test",
            title="Test Document",
            s3_key="documents/test-id/original.pdf",
            user_id=uuid4(),
            correlation_id="corr-123",
            timestamp=datetime.now(timezone.utc),
            storage_config=StorageConfig(type="local", local_path="/custom/path"),
        )

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        # Mock pipeline components
        orchestrator.parser_factory.parse = AsyncMock(return_value=sample_extracted_text)
        orchestrator.segmenter.segment = MagicMock(return_value=[])
        orchestrator.segmenter.create_structure_map = MagicMock(return_value="{}")
        orchestrator.chunker.chunk_document = MagicMock(return_value=[])
        orchestrator.embedding_generator.generate_embeddings = AsyncMock(return_value=[])
        orchestrator.qdrant_client.upsert_chunks = AsyncMock()

        result = await orchestrator.process_document(event, "worker-1")

        # Should have called get_storage_client with local config
        mock_get_storage.assert_called()
        call_kwargs = mock_get_storage.call_args.kwargs
        assert call_kwargs["storage_type"] == "local"
        assert call_kwargs["local_path"] == "/custom/path"


class TestPipelineOrchestratorReprocess:
    """Tests for reprocess_document method."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = MagicMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        mock_job = MagicMock()
        mock_job.stages_completed = []
        mock_job.stage_timings = {}

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_job

        db.execute = AsyncMock(return_value=mock_result)
        return db

    @pytest.fixture
    def mock_storage_client(self):
        """Create mock storage client."""
        client = MagicMock()
        client.download_object = AsyncMock(return_value=b"%PDF-1.4 test content")
        client.upload_bytes = AsyncMock()
        return client

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("httpx.AsyncClient")
    async def test_reprocess_document_fetches_from_registry(
        self, mock_http_client_class, mock_settings, mock_db, mock_storage_client
    ):
        """Test reprocess fetches document info from registry."""
        mock_settings.DOCUMENT_REGISTRY_URL = "http://registry:8000"
        mock_settings.S3_BUCKET = "test-bucket"
        mock_settings.ENABLE_KNOWLEDGE_EXTRACTION = False

        doc_id = uuid4()
        user_id = uuid4()

        # Mock registry response
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "document_id": str(doc_id),
            "content_hash": "hash123",
            "doi": "10.1234/test",
            "title": "Test Document",
            "artifact_pointers": {"pdf": f"documents/{doc_id}/original.pdf"},
            "provenance": [{"user_id": str(user_id)}],
            "source_metadata": {},
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_http_client_class.return_value = mock_client

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        # Mock process_document to avoid full execution
        orchestrator.process_document = AsyncMock(
            return_value=ProcessingResult(
                document_id=doc_id,
                success=True,
                chunk_count=5,
            )
        )

        result = await orchestrator.reprocess_document(doc_id)

        assert result.success is True
        mock_client.get.assert_called_once()

    @pytest.mark.asyncio
    @patch("services.document_processing.app.pipeline.orchestrator.settings")
    @patch("httpx.AsyncClient")
    async def test_reprocess_document_with_storage_config_in_metadata(
        self, mock_http_client_class, mock_settings, mock_db, mock_storage_client
    ):
        """Test reprocess extracts storage config from source_metadata."""
        mock_settings.DOCUMENT_REGISTRY_URL = "http://registry:8000"
        mock_settings.S3_BUCKET = "test-bucket"
        mock_settings.ENABLE_KNOWLEDGE_EXTRACTION = False

        doc_id = uuid4()
        user_id = uuid4()

        # Mock registry response with storage config
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "document_id": str(doc_id),
            "content_hash": "hash123",
            "doi": "10.1234/test",
            "title": "Test Document",
            "artifact_pointers": {"pdf": f"documents/{doc_id}/original.pdf"},
            "provenance": [{"user_id": str(user_id)}],
            "source_metadata": {
                "storage_config": {
                    "type": "local",
                    "local_path": "/data/uploads",
                }
            },
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()
        mock_http_client_class.return_value = mock_client

        orchestrator = PipelineOrchestrator(
            db=mock_db,
            storage_client=mock_storage_client,
        )

        # Capture the event passed to process_document
        captured_event = None

        async def capture_event(event, worker_id):
            nonlocal captured_event
            captured_event = event
            return ProcessingResult(document_id=doc_id, success=True)

        orchestrator.process_document = capture_event

        await orchestrator.reprocess_document(doc_id)

        assert captured_event is not None
        assert captured_event.storage_config is not None
        assert captured_event.storage_config.type == "local"
        assert captured_event.storage_config.local_path == "/data/uploads"
