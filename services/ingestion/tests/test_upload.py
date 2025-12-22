"""Tests for PDF upload handling."""

import io

import httpx
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

    @pytest.mark.asyncio
    async def test_upload_from_file_s3_error(self, handler, mock_s3_client):
        """Test upload fails when S3 upload fails."""
        mock_s3_client.upload_bytes.side_effect = Exception("S3 connection failed")

        content = b"%PDF-1.4 test content"
        file = io.BytesIO(content)

        result = await handler.upload_from_file(
            file=file,
            filename="test.pdf",
            document_id="doc-123",
        )

        assert result["success"] is False
        assert "Upload failed" in result["error"]
        assert "S3 connection failed" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_validation_failure(self, handler, mock_processor):
        """Test URL upload fails when PDF validation fails."""
        mock_processor.validate_pdf.return_value = {
            "valid": False,
            "error": "Corrupted PDF structure",
        }

        pdf_content = b"%PDF-1.4 corrupted content"

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

            assert result["success"] is False
            assert "Corrupted PDF structure" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_http_error(self, handler):
        """Test URL upload fails on HTTP error."""
        with patch(
            "services.ingestion.app.upload.handler.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 404

            http_error = httpx.HTTPStatusError(
                "Not Found",
                request=MagicMock(),
                response=mock_response,
            )
            mock_client.get = AsyncMock(side_effect=http_error)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await handler.upload_from_url(
                url="https://example.com/missing.pdf",
                document_id="doc-123",
            )

            assert result["success"] is False
            assert "HTTP 404" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_connection_error(self, handler):
        """Test URL upload fails on connection error."""
        with patch(
            "services.ingestion.app.upload.handler.httpx.AsyncClient"
        ) as mock_client_class:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            result = await handler.upload_from_url(
                url="https://unreachable.example.com/paper.pdf",
                document_id="doc-123",
            )

            assert result["success"] is False
            assert "Download failed" in result["error"]
            assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_upload_from_url_pdf_header_detection(self, handler, mock_s3_client):
        """Test URL upload detects PDF by header when content-type is wrong."""
        pdf_content = b"%PDF-1.4 test content"

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.content = pdf_content
            # Wrong content-type but valid PDF header
            mock_response.headers = {"content-type": "application/octet-stream"}
            mock_response.raise_for_status = MagicMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await handler.upload_from_url(
                url="https://example.com/paper.pdf",
                document_id="doc-123",
            )

            # Should succeed because content starts with %PDF
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_check_existing_error(self, handler, mock_s3_client):
        """Test check_existing returns None on error."""
        mock_s3_client.list_objects.side_effect = Exception("S3 error")

        result = await handler.check_existing("abc123hash")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_download_url_error(self, handler, mock_s3_client):
        """Test get_download_url returns None on error."""
        mock_s3_client.generate_presigned_url.side_effect = Exception("URL generation failed")

        result = await handler.get_download_url(
            s3_key="documents/doc-123/test.pdf",
            expires_in=3600,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_pdf_error(self, handler, mock_s3_client):
        """Test delete_pdf returns False on error."""
        mock_s3_client.delete_object.side_effect = Exception("Delete failed")

        result = await handler.delete_pdf("documents/doc-123/test.pdf")

        assert result is False

    @pytest.mark.asyncio
    async def test_upload_from_file_returns_size_and_page_count(self, handler, mock_s3_client, mock_processor):
        """Test upload_from_file returns correct size and page count."""
        mock_processor.validate_pdf.return_value = {
            "valid": True,
            "page_count": 25,
        }

        content = b"%PDF-1.4 test content with some data"
        file = io.BytesIO(content)

        result = await handler.upload_from_file(
            file=file,
            filename="document.pdf",
            document_id="doc-456",
        )

        assert result["success"] is True
        assert result["size_bytes"] == len(content)
        assert result["page_count"] == 25
        assert result["content_hash"] is not None

    @pytest.mark.asyncio
    async def test_upload_from_url_returns_metadata(self, handler, mock_s3_client, mock_processor):
        """Test upload_from_url returns source URL and metadata."""
        mock_processor.validate_pdf.return_value = {
            "valid": True,
            "page_count": 15,
        }

        pdf_content = b"%PDF-1.4 downloaded content"
        source_url = "https://arxiv.org/pdf/2401.12345.pdf"

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
                url=source_url,
                document_id="doc-789",
            )

            assert result["success"] is True
            assert result["source_url"] == source_url
            assert result["page_count"] == 15
            assert result["size_bytes"] == len(pdf_content)

    @pytest.mark.asyncio
    async def test_check_existing_searches_by_hash(self, handler, mock_s3_client):
        """Test check_existing searches for hash in object keys."""
        mock_s3_client.list_objects.return_value = [
            {"Key": "documents/doc-001/different_hash.pdf"},
            {"Key": "documents/doc-002/abc123hash.pdf"},
            {"Key": "documents/doc-003/yet_another.pdf"},
        ]

        result = await handler.check_existing("abc123hash")

        assert result == "documents/doc-002/abc123hash.pdf"

    @pytest.mark.asyncio
    async def test_get_download_url_with_custom_expiry(self, handler, mock_s3_client):
        """Test get_download_url passes custom expiry time."""
        mock_s3_client.generate_presigned_url.return_value = "https://example.com/signed"

        result = await handler.get_download_url(
            s3_key="documents/doc-123/test.pdf",
            expires_in=7200,
        )

        assert result == "https://example.com/signed"
        mock_s3_client.generate_presigned_url.assert_called_once()
        call_kwargs = mock_s3_client.generate_presigned_url.call_args[1]
        assert call_kwargs["expires_in"] == 7200
