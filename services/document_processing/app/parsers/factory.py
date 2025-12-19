"""Parser factory for routing to appropriate document parser."""

from typing import Protocol, runtime_checkable

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import ExtractedText
from services.document_processing.app.parsers.docling_parser import (
    DoclingParser,
    FileType,
    detect_file_type,
)
from services.document_processing.app.parsers.grobid import GrobidParser
from shared.utils.logging import get_logger

logger = get_logger(__name__)


@runtime_checkable
class DocumentParser(Protocol):
    """Protocol for document parsers."""

    async def parse_pdf(self, pdf_content: bytes) -> ExtractedText:
        """Parse PDF content."""
        ...

    async def check_health(self) -> bool:
        """Check parser health."""
        ...


class ParserFactory:
    """Factory for creating document parsers based on file type and configuration.

    Routing logic:
    - If Docling is enabled and available: Use Docling for all supported formats
    - For PDFs when GROBID is available: Can use GROBID as fallback for scientific papers
    - Non-PDF formats: Only Docling supports these
    """

    def __init__(
        self,
        docling_enabled: bool | None = None,
        prefer_grobid_for_scientific: bool = False,
    ):
        """Initialize parser factory.

        Args:
            docling_enabled: Override for Docling enabled setting
            prefer_grobid_for_scientific: Prefer GROBID for scientific PDFs
        """
        self.docling_enabled = (
            docling_enabled if docling_enabled is not None else settings.DOCLING_ENABLED
        )
        self.prefer_grobid_for_scientific = prefer_grobid_for_scientific

        # Lazy-initialized parsers
        self._docling_parser: DoclingParser | None = None
        self._grobid_parser: GrobidParser | None = None

    def get_docling_parser(self) -> DoclingParser:
        """Get or create Docling parser instance."""
        if self._docling_parser is None:
            self._docling_parser = DoclingParser()
        return self._docling_parser

    def get_grobid_parser(self) -> GrobidParser:
        """Get or create GROBID parser instance."""
        if self._grobid_parser is None:
            self._grobid_parser = GrobidParser()
        return self._grobid_parser

    async def parse(
        self,
        content: bytes,
        filename: str | None = None,
        file_type: FileType | None = None,
        use_grobid: bool = False,
    ) -> ExtractedText:
        """Parse document using appropriate parser.

        Args:
            content: Document content bytes
            filename: Original filename (for type detection)
            file_type: Explicit file type (overrides detection)
            use_grobid: Force use of GROBID for PDF

        Returns:
            Extracted text with sections and references
        """
        # Detect file type if not provided
        if file_type is None:
            file_type = detect_file_type(filename, content)

        logger.info(
            "parser_factory_parse",
            file_type=file_type.value,
            docling_enabled=self.docling_enabled,
            use_grobid=use_grobid,
            filename=filename,
        )

        # For PDF files
        if file_type == FileType.PDF:
            return await self._parse_pdf(content, use_grobid=use_grobid)

        # For non-PDF formats, must use Docling
        if not self.docling_enabled:
            raise ValueError(
                f"Cannot parse {file_type.value} files without Docling. "
                "Enable Docling or convert to PDF first."
            )

        parser = self.get_docling_parser()
        return await parser.parse(content, filename=filename, file_type=file_type)

    async def _parse_pdf(
        self,
        content: bytes,
        use_grobid: bool = False,
    ) -> ExtractedText:
        """Parse PDF with appropriate parser.

        Args:
            content: PDF content bytes
            use_grobid: Force use of GROBID

        Returns:
            Extracted text
        """
        # If GROBID is requested or preferred for scientific papers
        if use_grobid or (self.prefer_grobid_for_scientific and await self._is_grobid_available()):
            logger.info("using_grobid_parser")
            parser = self.get_grobid_parser()
            return await parser.parse_pdf(content)

        # Use Docling if enabled
        if self.docling_enabled:
            logger.info("using_docling_parser")
            parser = self.get_docling_parser()
            return await parser.parse_pdf(content)

        # Fall back to GROBID
        logger.info("using_grobid_parser_fallback")
        parser = self.get_grobid_parser()
        return await parser.parse_pdf(content)

    async def _is_grobid_available(self) -> bool:
        """Check if GROBID service is available."""
        try:
            parser = self.get_grobid_parser()
            return await parser.check_health()
        except Exception:
            return False

    async def check_health(self) -> dict[str, bool]:
        """Check health of all parsers.

        Returns:
            Dict of parser name to health status
        """
        health = {}

        # Check Docling
        if self.docling_enabled:
            try:
                parser = self.get_docling_parser()
                health["docling"] = await parser.check_health()
            except Exception as e:
                logger.warning("docling_health_check_failed", error=str(e))
                health["docling"] = False

        # Check GROBID
        try:
            parser = self.get_grobid_parser()
            health["grobid"] = await parser.check_health()
        except Exception as e:
            logger.warning("grobid_health_check_failed", error=str(e))
            health["grobid"] = False

        return health

    def get_supported_formats(self) -> list[str]:
        """Get list of supported file formats.

        Returns:
            List of supported file extensions
        """
        if self.docling_enabled:
            # Docling supports all formats
            return [
                ".pdf",
                ".docx",
                ".doc",
                ".pptx",
                ".ppt",
                ".xlsx",
                ".xls",
                ".html",
                ".htm",
                ".png",
                ".jpg",
                ".jpeg",
                ".tiff",
                ".tif",
                ".md",
                ".markdown",
            ]
        else:
            # GROBID only supports PDF
            return [".pdf"]


# Global factory instance
_parser_factory: ParserFactory | None = None


def get_parser_factory() -> ParserFactory:
    """Get the global parser factory instance."""
    global _parser_factory
    if _parser_factory is None:
        _parser_factory = ParserFactory()
    return _parser_factory


def reset_parser_factory() -> None:
    """Reset the global parser factory (for testing)."""
    global _parser_factory
    _parser_factory = None
