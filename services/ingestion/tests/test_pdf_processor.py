"""Tests for PDF processor."""

import sys
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest


@contextmanager
def mock_pymupdf(mock_fitz):
    """Context manager to safely mock PyMuPDF in the processor module."""
    import services.ingestion.app.upload.processor as proc_module

    # Save original state
    original_available = proc_module.PYMUPDF_AVAILABLE
    original_fitz = getattr(proc_module, "fitz", None)
    original_sys_fitz = sys.modules.get("fitz")

    # Inject mock
    sys.modules["fitz"] = mock_fitz
    proc_module.PYMUPDF_AVAILABLE = True
    proc_module.fitz = mock_fitz

    try:
        yield proc_module
    finally:
        # Restore original state
        proc_module.PYMUPDF_AVAILABLE = original_available
        if original_fitz is not None:
            proc_module.fitz = original_fitz
        elif hasattr(proc_module, "fitz"):
            delattr(proc_module, "fitz")

        if original_sys_fitz is not None:
            sys.modules["fitz"] = original_sys_fitz
        elif "fitz" in sys.modules:
            del sys.modules["fitz"]


class TestPDFProcessorValidation:
    """Tests for PDF validation."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance."""
        from services.ingestion.app.upload.processor import PDFProcessor

        return PDFProcessor()

    @pytest.fixture
    def valid_pdf_content(self):
        """Create minimal valid PDF content."""
        # Minimal PDF structure
        return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
196
%%EOF"""

    @pytest.mark.asyncio
    async def test_validate_pdf_file_too_large(self, processor):
        """Test validation fails for files exceeding size limit."""
        # Create content larger than MAX_FILE_SIZE
        large_content = b"%PDF-1.4" + b"x" * (processor.MAX_FILE_SIZE + 1)

        result = await processor.validate_pdf(large_content)

        assert result["valid"] is False
        assert "too large" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_pdf_invalid_header(self, processor):
        """Test validation fails for non-PDF files."""
        result = await processor.validate_pdf(b"This is not a PDF file")

        assert result["valid"] is False
        assert "missing header" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_pdf_empty_content(self, processor):
        """Test validation fails for empty content."""
        result = await processor.validate_pdf(b"")

        assert result["valid"] is False
        assert "missing header" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_pdf_valid_header_basic(self, processor, valid_pdf_content):
        """Test basic validation passes for valid PDF header."""
        # This test will use PyMuPDF if available, otherwise basic validation
        result = await processor.validate_pdf(valid_pdf_content)

        # Should be valid regardless of PyMuPDF availability
        assert result["valid"] is True


class TestPDFProcessorWithMockedPyMuPDF:
    """Tests for PDF processing with mocked PyMuPDF."""

    @pytest.fixture
    def mock_fitz(self):
        """Create and register mock fitz module."""
        mock_fitz_module = MagicMock()
        return mock_fitz_module

    @pytest.fixture
    def mock_doc(self):
        """Create mock fitz document."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.is_encrypted = False
        mock_doc.metadata = {
            "title": "Test Document",
            "author": "Test Author",
            "subject": "Test Subject",
            "creator": "Test Creator",
            "producer": "Test Producer",
            "keywords": "test, pdf",
            "creationDate": "D:20240101120000",
            "modDate": "D:20240115120000",
        }
        mock_doc.close = MagicMock()

        # Mock page
        mock_page = MagicMock()
        mock_page.get_text.return_value = "Page text content"
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)

        return mock_doc

    @pytest.fixture
    def processor_with_pymupdf(self, mock_fitz, mock_doc):
        """Create PDFProcessor with mocked PyMuPDF."""
        import services.ingestion.app.upload.processor as proc_module

        # Save original state
        original_available = proc_module.PYMUPDF_AVAILABLE
        original_fitz = getattr(proc_module, "fitz", None)
        original_sys_fitz = sys.modules.get("fitz")

        # Setup mock fitz.open to return mock_doc
        mock_fitz.open = MagicMock(return_value=mock_doc)

        # Inject mock
        sys.modules["fitz"] = mock_fitz
        proc_module.PYMUPDF_AVAILABLE = True
        proc_module.fitz = mock_fitz

        from services.ingestion.app.upload.processor import PDFProcessor

        processor = PDFProcessor()

        yield processor, mock_fitz, mock_doc

        # Restore original state
        proc_module.PYMUPDF_AVAILABLE = original_available
        if original_fitz is not None:
            proc_module.fitz = original_fitz
        elif hasattr(proc_module, "fitz"):
            delattr(proc_module, "fitz")

        if original_sys_fitz is not None:
            sys.modules["fitz"] = original_sys_fitz
        elif "fitz" in sys.modules:
            del sys.modules["fitz"]

    @pytest.mark.asyncio
    async def test_validate_with_pymupdf_success(self, processor_with_pymupdf):
        """Test successful validation with PyMuPDF."""
        processor, mock_fitz, mock_doc = processor_with_pymupdf

        result = await processor._validate_with_pymupdf(b"%PDF-1.4 content")

        assert result["valid"] is True
        assert result["page_count"] == 5
        assert result["metadata"]["title"] == "Test Document"
        assert result["metadata"]["author"] == "Test Author"
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_with_pymupdf_too_many_pages(self, mock_fitz):
        """Test validation fails for too many pages."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1001)  # Over MAX_PAGE_COUNT
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor._validate_with_pymupdf(b"%PDF-1.4 content")

        assert result["valid"] is False
        assert "too many pages" in result["error"].lower()
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_with_pymupdf_encrypted(self, mock_fitz):
        """Test validation fails for encrypted PDFs."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.is_encrypted = True
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor._validate_with_pymupdf(b"%PDF-1.4 content")

        assert result["valid"] is False
        assert "encrypted" in result["error"].lower()
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_validate_with_pymupdf_error(self, mock_fitz):
        """Test validation handles parsing errors."""
        mock_fitz.open = MagicMock(side_effect=Exception("Corrupted PDF"))

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor._validate_with_pymupdf(b"%PDF-1.4 corrupted")

        assert result["valid"] is False
        assert "parsing failed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_validate_with_pymupdf_no_metadata(self, mock_fitz):
        """Test validation handles PDFs with no metadata."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.is_encrypted = False
        mock_doc.metadata = None
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor._validate_with_pymupdf(b"%PDF-1.4 content")

        assert result["valid"] is True
        assert result["page_count"] == 1
        assert result["metadata"]["title"] is None


class TestPDFProcessorExtractText:
    """Tests for text extraction."""

    @pytest.fixture
    def mock_fitz(self):
        """Create mock fitz module."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_extract_text_all_pages(self, mock_fitz):
        """Test extracting text from all pages."""
        mock_pages = [MagicMock(), MagicMock(), MagicMock()]
        mock_pages[0].get_text.return_value = "Page 1 text"
        mock_pages[1].get_text.return_value = "Page 2 text"
        mock_pages[2].get_text.return_value = "Page 3 text"

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=3)
        mock_doc.__getitem__ = lambda self, idx: mock_pages[idx]
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_text(b"%PDF-1.4 content")

        assert "Page 1 text" in result
        assert "Page 2 text" in result
        assert "Page 3 text" in result
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_text_limited_pages(self, mock_fitz):
        """Test extracting text from limited pages."""
        mock_pages = [MagicMock(), MagicMock(), MagicMock()]
        mock_pages[0].get_text.return_value = "Page 1 text"
        mock_pages[1].get_text.return_value = "Page 2 text"
        mock_pages[2].get_text.return_value = "Page 3 text"

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=3)
        mock_doc.__getitem__ = lambda self, idx: mock_pages[idx]
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_text(b"%PDF-1.4 content", max_pages=2)

        assert "Page 1 text" in result
        assert "Page 2 text" in result
        assert "Page 3 text" not in result

    @pytest.mark.asyncio
    async def test_extract_text_error(self, mock_fitz):
        """Test text extraction handles errors."""
        mock_fitz.open = MagicMock(side_effect=Exception("Extraction failed"))

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            with pytest.raises(Exception, match="Extraction failed"):
                await processor.extract_text(b"%PDF-1.4 content")


class TestPDFProcessorExtractMetadata:
    """Tests for metadata extraction."""

    @pytest.fixture
    def mock_fitz(self):
        """Create mock fitz module."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_extract_metadata_success(self, mock_fitz):
        """Test successful metadata extraction."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=10)
        mock_doc.metadata = {
            "title": "Test Title",
            "author": "Test Author",
            "subject": "Test Subject",
            "keywords": "test, keywords",
            "creator": "Test Creator",
            "producer": "Test Producer",
            "creationDate": "D:20240101",
            "modDate": "D:20240115",
        }
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_metadata(b"%PDF-1.4 content")

        assert result["page_count"] == 10
        assert result["title"] == "Test Title"
        assert result["author"] == "Test Author"
        assert result["keywords"] == "test, keywords"
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_metadata_filters_empty(self, mock_fitz):
        """Test that empty metadata values are filtered out."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.metadata = MagicMock()
        mock_doc.metadata.get = lambda key: {
            "title": "Test Title",
            "author": "",  # Empty - should be filtered
            "subject": None,  # None - should be filtered
            "keywords": "keywords",
        }.get(key)
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_metadata(b"%PDF-1.4 content")

        assert "title" in result
        assert result["title"] == "Test Title"
        assert "author" not in result
        assert "subject" not in result
        assert "keywords" in result

    @pytest.mark.asyncio
    async def test_extract_metadata_error(self, mock_fitz):
        """Test metadata extraction handles errors gracefully."""
        mock_fitz.open = MagicMock(side_effect=Exception("Metadata extraction failed"))

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_metadata(b"%PDF-1.4 content")

        assert result == {}


class TestPDFProcessorGetPageCount:
    """Tests for page count extraction."""

    @pytest.fixture
    def mock_fitz(self):
        """Create mock fitz module."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_get_page_count_success(self, mock_fitz):
        """Test successful page count extraction."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=42)
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.get_page_count(b"%PDF-1.4 content")

        assert result == 42
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_page_count_error(self, mock_fitz):
        """Test page count returns None on error."""
        mock_fitz.open = MagicMock(side_effect=Exception("Failed to open"))

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.get_page_count(b"%PDF-1.4 content")

        assert result is None


class TestPDFProcessorExtractFirstPageText:
    """Tests for first page text extraction."""

    @pytest.fixture
    def mock_fitz(self):
        """Create mock fitz module."""
        return MagicMock()

    @pytest.mark.asyncio
    async def test_extract_first_page_success(self, mock_fitz):
        """Test successful first page text extraction."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "  First page content  "

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=5)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_first_page_text(b"%PDF-1.4 content")

        assert result == "First page content"  # Stripped
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_first_page_empty_document(self, mock_fitz):
        """Test first page extraction returns None for empty document."""
        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=0)
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_first_page_text(b"%PDF-1.4 content")

        assert result is None
        mock_doc.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_first_page_empty_text(self, mock_fitz):
        """Test first page extraction returns None for empty text."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = ""

        mock_doc = MagicMock()
        mock_doc.__len__ = MagicMock(return_value=1)
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_doc.close = MagicMock()
        mock_fitz.open = MagicMock(return_value=mock_doc)

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_first_page_text(b"%PDF-1.4 content")

        assert result is None

    @pytest.mark.asyncio
    async def test_extract_first_page_error(self, mock_fitz):
        """Test first page extraction returns None on error."""
        mock_fitz.open = MagicMock(side_effect=Exception("Failed to open"))

        with mock_pymupdf(mock_fitz):
            from services.ingestion.app.upload.processor import PDFProcessor

            processor = PDFProcessor()
            result = await processor.extract_first_page_text(b"%PDF-1.4 content")

        assert result is None


class TestPDFProcessorWithoutPyMuPDF:
    """Tests for behavior when PyMuPDF is unavailable."""

    @pytest.fixture
    def processor(self):
        """Create PDFProcessor instance."""
        from services.ingestion.app.upload.processor import PDFProcessor

        return PDFProcessor()

    @pytest.mark.asyncio
    async def test_validate_pdf_basic_validation(self, processor):
        """Test basic validation without PyMuPDF."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            result = await processor.validate_pdf(b"%PDF-1.4 some content")

            assert result["valid"] is True
            assert result["page_count"] is None
            assert "warning" in result
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_validate_pdf_invalid_still_detected(self, processor):
        """Test that invalid PDFs are still detected without PyMuPDF."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            result = await processor.validate_pdf(b"Not a PDF file")

            assert result["valid"] is False
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_extract_text_raises_without_pymupdf(self, processor):
        """Test extract_text raises when PyMuPDF unavailable."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            with pytest.raises(RuntimeError, match="PyMuPDF not available"):
                await processor.extract_text(b"%PDF-1.4 content")
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_extract_metadata_returns_empty_without_pymupdf(self, processor):
        """Test extract_metadata returns empty dict when PyMuPDF unavailable."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            metadata = await processor.extract_metadata(b"%PDF-1.4 content")
            assert metadata == {}
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_get_page_count_returns_none_without_pymupdf(self, processor):
        """Test get_page_count returns None when PyMuPDF unavailable."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            count = await processor.get_page_count(b"%PDF-1.4 content")
            assert count is None
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value

    @pytest.mark.asyncio
    async def test_extract_first_page_returns_none_without_pymupdf(self, processor):
        """Test extract_first_page_text returns None when PyMuPDF unavailable."""
        import services.ingestion.app.upload.processor as proc_module

        original_value = proc_module.PYMUPDF_AVAILABLE
        try:
            proc_module.PYMUPDF_AVAILABLE = False
            text = await processor.extract_first_page_text(b"%PDF-1.4 content")
            assert text is None
        finally:
            proc_module.PYMUPDF_AVAILABLE = original_value


class TestPDFProcessorConstants:
    """Tests for PDFProcessor constants."""

    def test_max_file_size(self):
        """Test MAX_FILE_SIZE constant."""
        from services.ingestion.app.upload.processor import PDFProcessor

        processor = PDFProcessor()
        # 100 MB
        assert processor.MAX_FILE_SIZE == 100 * 1024 * 1024

    def test_max_page_count(self):
        """Test MAX_PAGE_COUNT constant."""
        from services.ingestion.app.upload.processor import PDFProcessor

        processor = PDFProcessor()
        assert processor.MAX_PAGE_COUNT == 1000
