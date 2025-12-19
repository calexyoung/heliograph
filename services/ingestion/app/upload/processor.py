"""PDF processing and validation."""

import io
from typing import Any

from shared.utils.logging import get_logger

logger = get_logger(__name__)

# Try to import PyMuPDF (fitz) for PDF processing
try:
    import fitz

    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    logger.warning("pymupdf_not_available", message="PDF validation limited")


class PDFProcessor:
    """Process and validate PDF files."""

    # Maximum file size (100 MB)
    MAX_FILE_SIZE = 100 * 1024 * 1024

    # Maximum page count
    MAX_PAGE_COUNT = 1000

    async def validate_pdf(self, content: bytes) -> dict[str, Any]:
        """Validate PDF content.

        Args:
            content: PDF file bytes

        Returns:
            Validation result with metadata
        """
        # Check file size
        if len(content) > self.MAX_FILE_SIZE:
            return {
                "valid": False,
                "error": f"File too large: {len(content)} bytes (max {self.MAX_FILE_SIZE})",
            }

        # Check PDF header
        if not content.startswith(b"%PDF"):
            return {
                "valid": False,
                "error": "Not a valid PDF file (missing header)",
            }

        # Use PyMuPDF for detailed validation if available
        if PYMUPDF_AVAILABLE:
            return await self._validate_with_pymupdf(content)

        # Basic validation without PyMuPDF
        return {
            "valid": True,
            "page_count": None,
            "warning": "Detailed validation unavailable",
        }

    async def _validate_with_pymupdf(self, content: bytes) -> dict[str, Any]:
        """Validate PDF using PyMuPDF.

        Args:
            content: PDF file bytes

        Returns:
            Validation result with metadata
        """
        try:
            # Open PDF from bytes
            doc = fitz.open(stream=content, filetype="pdf")

            page_count = len(doc)

            # Check page count
            if page_count > self.MAX_PAGE_COUNT:
                doc.close()
                return {
                    "valid": False,
                    "error": f"Too many pages: {page_count} (max {self.MAX_PAGE_COUNT})",
                }

            # Check if PDF is encrypted
            if doc.is_encrypted:
                doc.close()
                return {
                    "valid": False,
                    "error": "PDF is encrypted",
                }

            # Extract basic metadata
            metadata = doc.metadata or {}

            doc.close()

            return {
                "valid": True,
                "page_count": page_count,
                "metadata": {
                    "title": metadata.get("title"),
                    "author": metadata.get("author"),
                    "subject": metadata.get("subject"),
                    "creator": metadata.get("creator"),
                    "producer": metadata.get("producer"),
                },
            }

        except Exception as e:
            logger.error("pdf_validation_error", error=str(e))
            return {
                "valid": False,
                "error": f"PDF parsing failed: {str(e)}",
            }

    async def extract_text(self, content: bytes, max_pages: int | None = None) -> str:
        """Extract text from PDF.

        Args:
            content: PDF file bytes
            max_pages: Maximum pages to extract (None for all)

        Returns:
            Extracted text
        """
        if not PYMUPDF_AVAILABLE:
            raise RuntimeError("PyMuPDF not available for text extraction")

        try:
            doc = fitz.open(stream=content, filetype="pdf")

            text_parts = []
            pages_to_process = min(len(doc), max_pages) if max_pages else len(doc)

            for page_num in range(pages_to_process):
                page = doc[page_num]
                text = page.get_text()
                text_parts.append(text)

            doc.close()

            return "\n\n".join(text_parts)

        except Exception as e:
            logger.error("pdf_text_extraction_error", error=str(e))
            raise

    async def extract_metadata(self, content: bytes) -> dict[str, Any]:
        """Extract metadata from PDF.

        Args:
            content: PDF file bytes

        Returns:
            PDF metadata
        """
        if not PYMUPDF_AVAILABLE:
            return {}

        try:
            doc = fitz.open(stream=content, filetype="pdf")

            metadata = {
                "page_count": len(doc),
                "title": doc.metadata.get("title"),
                "author": doc.metadata.get("author"),
                "subject": doc.metadata.get("subject"),
                "keywords": doc.metadata.get("keywords"),
                "creator": doc.metadata.get("creator"),
                "producer": doc.metadata.get("producer"),
                "creation_date": doc.metadata.get("creationDate"),
                "mod_date": doc.metadata.get("modDate"),
            }

            doc.close()

            # Clean empty values
            return {k: v for k, v in metadata.items() if v}

        except Exception as e:
            logger.error("pdf_metadata_extraction_error", error=str(e))
            return {}

    async def get_page_count(self, content: bytes) -> int | None:
        """Get page count from PDF.

        Args:
            content: PDF file bytes

        Returns:
            Page count or None
        """
        if not PYMUPDF_AVAILABLE:
            return None

        try:
            doc = fitz.open(stream=content, filetype="pdf")
            count = len(doc)
            doc.close()
            return count
        except Exception:
            return None

    async def extract_first_page_text(self, content: bytes) -> str | None:
        """Extract text from first page for quick preview.

        Args:
            content: PDF file bytes

        Returns:
            First page text or None
        """
        if not PYMUPDF_AVAILABLE:
            return None

        try:
            doc = fitz.open(stream=content, filetype="pdf")

            if len(doc) == 0:
                doc.close()
                return None

            text = doc[0].get_text()
            doc.close()

            return text.strip() if text else None

        except Exception as e:
            logger.error("first_page_extraction_error", error=str(e))
            return None
