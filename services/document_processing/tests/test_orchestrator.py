"""Tests for pipeline orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.document_processing.app.parsers.factory import ParserFactory


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
