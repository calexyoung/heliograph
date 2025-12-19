"""Tests for PDF upload handling."""

import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.ingestion.app.upload.handler import UploadHandler
from services.ingestion.app.upload.processor import PDFProcessor


class TestPDFProcessor:
    """Tests for PDF processor."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        return PDFProcessor()

    @pytest.mark.asyncio
    async def test_validate_pdf_invalid_header(self, processor):
        """Test validation fails for non-PDF."""
        content = b"This is not a PDF file"
        result = await processor.validate_pdf(content)

        assert result["valid"] is False
        assert "header" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_pdf_valid_header(self, processor):
        """Test validation passes for valid PDF header."""
        # Minimal valid PDF header
        content = b"%PDF-1.4 test content"
        result = await processor.validate_pdf(content)

        # Without PyMuPDF, basic validation should pass
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_pdf_too_large(self, processor):
        """Test validation fails for oversized file."""
        # Create content larger than max size
        content = b"%PDF" + b"x" * (processor.MAX_FILE_SIZE + 1)
        result = await processor.validate_pdf(content)

        assert result["valid"] is False
        assert "large" in result["error"].lower()


class TestUploadHandler:
    """Tests for upload handler."""

    @pytest.fixture
    def mock_s3_client(self):
        """Create mock S3 client."""
        mock = AsyncMock()
        mock.upload_bytes = AsyncMock()
        mock.list_objects = AsyncMock(return_value=[])
        mock.generate_presigned_url = AsyncMock(return_value="https://example.com/presigned")
        mock.delete_object = AsyncMock()
        return mock

    @pytest.fixture
    def mock_processor(self):
        """Create mock PDF processor."""
        mock = AsyncMock(spec=PDFProcessor)
        mock.validate_pdf = AsyncMock(return_value={"valid": True, "page_count": 10})
        return mock

    @pytest.fixture
    def handler(self, mock_s3_client, mock_processor):
        """Create handler with mocks."""
        handler = UploadHandler(
            s3_client=mock_s3_client,
            pdf_processor=mock_processor,
        )
        return handler

    @pytest.mark.asyncio
    async def test_upload_from_file_success(self, handler, mock_s3_client):
        """Test successful file upload."""
        content = b"%PDF-1.4 test content"
        file = io.BytesIO(content)

        result = await handler.upload_from_file(
            file=file,
            filename="test.pdf",
            document_id="doc-123",
        )

        assert result["success"] is True
        assert "s3_key" in result
        assert "content_hash" in result
        assert result["page_count"] == 10
        mock_s3_client.upload_bytes.assert_called_once()

    @pytest.mark.asyncio
    async def test_upload_from_file_validation_failure(self, handler, mock_processor):
        """Test upload fails when validation fails."""
        mock_processor.validate_pdf.return_value = {
            "valid": False,
            "error": "Invalid PDF",
        }

        content = b"not a pdf"
        file = io.BytesIO(content)

        result = await handler.upload_from_file(
            file=file,
            filename="test.pdf",
            document_id="doc-123",
        )

        assert result["success"] is False
        assert "Invalid PDF" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_success(self, handler, mock_s3_client):
        """Test successful URL upload."""
        pdf_content = b"%PDF-1.4 test content"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = pdf_content
            mock_response.headers = {"content-type": "application/pdf"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await handler.upload_from_url(
                url="https://example.com/paper.pdf",
                document_id="doc-123",
            )

            assert result["success"] is True
            assert "s3_key" in result
            assert result["source_url"] == "https://example.com/paper.pdf"

    @pytest.mark.asyncio
    async def test_upload_from_url_not_pdf(self, handler):
        """Test URL upload fails for non-PDF."""
        html_content = b"<html>Not a PDF</html>"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = html_content
            mock_response.headers = {"content-type": "text/html"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await handler.upload_from_url(
                url="https://example.com/page.html",
                document_id="doc-123",
            )

            assert result["success"] is False
            assert "Not a PDF" in result["error"]

    @pytest.mark.asyncio
    async def test_check_existing_found(self, handler, mock_s3_client):
        """Test finding existing PDF by hash."""
        mock_s3_client.list_objects.return_value = [
            {"Key": "documents/doc-123/abc123hash.pdf"}
        ]

        result = await handler.check_existing("abc123hash")

        assert result == "documents/doc-123/abc123hash.pdf"

    @pytest.mark.asyncio
    async def test_check_existing_not_found(self, handler, mock_s3_client):
        """Test not finding existing PDF."""
        mock_s3_client.list_objects.return_value = []

        result = await handler.check_existing("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url(self, handler, mock_s3_client):
        """Test generating download URL."""
        result = await handler.get_download_url(
            s3_key="documents/doc-123/test.pdf",
            expires_in=3600,
        )

        assert result == "https://example.com/presigned"
        mock_s3_client.generate_presigned_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_pdf(self, handler, mock_s3_client):
        """Test deleting PDF."""
        result = await handler.delete_pdf("documents/doc-123/test.pdf")

        assert result is True
        mock_s3_client.delete_object.assert_called_once()
