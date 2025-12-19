"""Docling document parsing - supports PDF, DOCX, PPTX, XLSX, HTML, images."""

import re
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedReference,
    ParsedSection,
    SectionType,
)
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class FileType(str, Enum):
    """Supported file types for Docling parser."""

    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    HTML = "html"
    IMAGE = "image"  # PNG, JPEG, TIFF, etc.
    MARKDOWN = "markdown"
    ASCIIDOC = "asciidoc"


# Map file extensions to FileType
EXTENSION_MAP: dict[str, FileType] = {
    ".pdf": FileType.PDF,
    ".docx": FileType.DOCX,
    ".doc": FileType.DOCX,  # Will be converted
    ".pptx": FileType.PPTX,
    ".ppt": FileType.PPTX,  # Will be converted
    ".xlsx": FileType.XLSX,
    ".xls": FileType.XLSX,  # Will be converted
    ".html": FileType.HTML,
    ".htm": FileType.HTML,
    ".png": FileType.IMAGE,
    ".jpg": FileType.IMAGE,
    ".jpeg": FileType.IMAGE,
    ".tiff": FileType.IMAGE,
    ".tif": FileType.IMAGE,
    ".bmp": FileType.IMAGE,
    ".md": FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".adoc": FileType.ASCIIDOC,
}


def detect_file_type(filename: str | None, content: bytes | None = None) -> FileType:
    """Detect file type from filename or content.

    Args:
        filename: Original filename with extension
        content: File content bytes (for magic number detection)

    Returns:
        Detected file type
    """
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in EXTENSION_MAP:
            return EXTENSION_MAP[ext]

    # Fall back to magic number detection for content
    if content:
        # PDF magic number
        if content[:4] == b"%PDF":
            return FileType.PDF
        # PNG magic number
        if content[:8] == b"\x89PNG\r\n\x1a\n":
            return FileType.IMAGE
        # JPEG magic numbers
        if content[:2] == b"\xff\xd8":
            return FileType.IMAGE
        # TIFF magic numbers
        if content[:4] in (b"II*\x00", b"MM\x00*"):
            return FileType.IMAGE
        # ZIP-based formats (DOCX, PPTX, XLSX)
        if content[:4] == b"PK\x03\x04":
            # Need to check internal structure for specific type
            return FileType.DOCX  # Default to DOCX, will be validated

    return FileType.PDF  # Default


class DoclingParser:
    """Document parser using IBM's Docling library.

    Supports: PDF, DOCX, PPTX, XLSX, HTML, images (with OCR).
    """

    def __init__(
        self,
        ocr_enabled: bool | None = None,
        table_structure: bool | None = None,
        timeout: int | None = None,
    ):
        """Initialize Docling parser.

        Args:
            ocr_enabled: Enable OCR for scanned documents
            table_structure: Enable table structure extraction
            timeout: Processing timeout in seconds
        """
        self.ocr_enabled = ocr_enabled if ocr_enabled is not None else settings.DOCLING_OCR_ENABLED
        self.table_structure = (
            table_structure if table_structure is not None else settings.DOCLING_TABLE_STRUCTURE
        )
        self.timeout = timeout or settings.DOCLING_TIMEOUT
        self._converter = None

    def _get_converter(self):
        """Lazily initialize the Docling converter."""
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter, PdfFormatOption
                from docling.datamodel.pipeline_options import PdfPipelineOptions
                from docling.datamodel.base_models import InputFormat

                # Configure pipeline options
                pipeline_options = PdfPipelineOptions()
                pipeline_options.do_ocr = self.ocr_enabled
                pipeline_options.do_table_structure = self.table_structure

                # Create converter with options
                self._converter = DocumentConverter(
                    format_options={
                        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                    }
                )

                logger.info(
                    "docling_converter_initialized",
                    ocr_enabled=self.ocr_enabled,
                    table_structure=self.table_structure,
                )
            except ImportError as e:
                logger.error("docling_import_error", error=str(e))
                raise ImportError(
                    "Docling is not installed. Install with: pip install docling"
                ) from e

        return self._converter

    async def parse(
        self,
        content: bytes,
        filename: str | None = None,
        file_type: FileType | None = None,
    ) -> ExtractedText:
        """Parse document content using Docling.

        Args:
            content: Document content bytes
            filename: Original filename (for type detection)
            file_type: Explicit file type (overrides detection)

        Returns:
            Extracted text with sections and references
        """
        if file_type is None:
            file_type = detect_file_type(filename, content)

        logger.info(
            "docling_parse_start",
            file_type=file_type.value,
            content_size=len(content),
            filename=filename,
        )

        try:
            return await self._parse_with_docling(content, filename, file_type)
        except ImportError:
            # Docling not available, fall back to basic extraction
            logger.warning("docling_not_available_falling_back")
            return await self._fallback_parse(content, file_type)
        except Exception as e:
            logger.error(
                "docling_parse_error",
                error=str(e),
                file_type=file_type.value,
            )
            # Fall back to basic extraction
            return await self._fallback_parse(content, file_type)

    async def _parse_with_docling(
        self,
        content: bytes,
        filename: str | None,
        file_type: FileType,
    ) -> ExtractedText:
        """Parse document using Docling library.

        Args:
            content: Document bytes
            filename: Original filename
            file_type: Detected file type

        Returns:
            Extracted text structure
        """
        import asyncio
        from tempfile import NamedTemporaryFile

        converter = self._get_converter()

        # Docling requires a file path, so we create a temp file
        suffix = f".{file_type.value}" if file_type != FileType.IMAGE else ".pdf"
        if filename:
            suffix = Path(filename).suffix or suffix

        # Run conversion in thread pool to avoid blocking
        def convert_sync():
            with NamedTemporaryFile(suffix=suffix, delete=True) as tmp:
                tmp.write(content)
                tmp.flush()
                result = converter.convert(tmp.name)
                return result

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, convert_sync)

        # Extract document from result
        doc = result.document

        # Convert to our format
        return self._convert_docling_result(doc, file_type)

    def _convert_docling_result(self, doc, file_type: FileType) -> ExtractedText:
        """Convert Docling document to our ExtractedText format.

        Args:
            doc: Docling document result
            file_type: Source file type

        Returns:
            ExtractedText structure
        """
        # Export to markdown for full text
        full_text = doc.export_to_markdown()

        # Extract sections from document structure
        sections = self._extract_sections_from_docling(doc)

        # If no sections extracted, create a single section with full text
        if not sections:
            sections = [
                ParsedSection(
                    section_type=SectionType.OTHER,
                    title=None,
                    text=full_text,
                    char_offset_start=0,
                    char_offset_end=len(full_text),
                )
            ]

        # Extract references if available
        references = self._extract_references_from_docling(doc)

        # Get page count
        page_count = self._get_page_count_from_docling(doc)

        # Extract metadata
        metadata = self._extract_metadata_from_docling(doc, file_type)

        return ExtractedText(
            full_text=full_text,
            sections=sections,
            references=references,
            page_count=page_count,
            metadata=metadata,
        )

    def _extract_sections_from_docling(self, doc) -> list[ParsedSection]:
        """Extract sections from Docling document.

        Args:
            doc: Docling document

        Returns:
            List of parsed sections
        """
        sections = []
        char_offset = 0
        current_section_title = None
        current_section_text = []
        current_section_type = SectionType.OTHER

        try:
            # Iterate through document items with level info
            for item, level in doc.iterate_items(with_groups=True):
                label = getattr(item, "label", None)
                text = str(getattr(item, "text", "") or "").strip()
                item_type_name = type(item).__name__

                # Skip empty items and groups
                if not text or item_type_name == "GroupItem":
                    continue

                # Skip page headers/footers
                if label in ("page_header", "page_footer"):
                    continue

                # Handle section headers - start a new section
                if label == "section_header" or item_type_name == "SectionHeaderItem":
                    # Save previous section if exists
                    if current_section_text or current_section_title:
                        section_text = "\n".join(current_section_text)
                        sections.append(ParsedSection(
                            section_type=current_section_type,
                            title=current_section_title,
                            text=section_text,
                            char_offset_start=char_offset,
                            char_offset_end=char_offset + len(section_text),
                        ))
                        char_offset += len(section_text) + 2

                    # Start new section
                    current_section_title = text
                    current_section_type = self._map_section_title_to_type(text)
                    current_section_text = []

                # Handle text content
                elif label in ("text", "list_item", "caption"):
                    current_section_text.append(text)

                # Handle footnotes - add to current section
                elif label == "footnote":
                    current_section_text.append(f"[footnote] {text}")

            # Save final section
            if current_section_text or current_section_title:
                section_text = "\n".join(current_section_text)
                sections.append(ParsedSection(
                    section_type=current_section_type,
                    title=current_section_title,
                    text=section_text,
                    char_offset_start=char_offset,
                    char_offset_end=char_offset + len(section_text),
                ))

        except Exception as e:
            logger.warning("docling_section_extraction_error", error=str(e))

        return sections

    def _map_section_title_to_type(self, title: str) -> SectionType:
        """Map section title to section type.

        Args:
            title: Section title text

        Returns:
            SectionType enum
        """
        if not title:
            return SectionType.OTHER

        title_lower = title.lower()

        # Check for common section patterns
        if "abstract" in title_lower:
            return SectionType.ABSTRACT
        if "introduction" in title_lower:
            return SectionType.INTRODUCTION
        if any(x in title_lower for x in ("method", "material", "approach", "technique")):
            return SectionType.METHODS
        if "result" in title_lower:
            return SectionType.RESULTS
        if "discussion" in title_lower:
            return SectionType.DISCUSSION
        if "conclusion" in title_lower:
            return SectionType.CONCLUSION
        if any(x in title_lower for x in ("reference", "bibliography")):
            return SectionType.REFERENCES
        if any(x in title_lower for x in ("acknowledgment", "acknowledgement")):
            return SectionType.ACKNOWLEDGMENTS
        if "appendix" in title_lower:
            return SectionType.APPENDIX

        return SectionType.OTHER

    def _map_docling_label_to_section_type(self, label) -> SectionType:
        """Map Docling label to our section type.

        Args:
            label: Docling document item label

        Returns:
            SectionType enum
        """
        if label is None:
            return SectionType.OTHER

        label_str = str(label).lower()

        if "abstract" in label_str:
            return SectionType.ABSTRACT
        if "introduction" in label_str:
            return SectionType.INTRODUCTION
        if "method" in label_str or "material" in label_str:
            return SectionType.METHODS
        if "result" in label_str:
            return SectionType.RESULTS
        if "discussion" in label_str:
            return SectionType.DISCUSSION
        if "conclusion" in label_str:
            return SectionType.CONCLUSION
        if "reference" in label_str or "bibliography" in label_str:
            return SectionType.REFERENCES
        if "acknowledgment" in label_str or "acknowledgement" in label_str:
            return SectionType.ACKNOWLEDGMENTS
        if "appendix" in label_str:
            return SectionType.APPENDIX
        if "title" in label_str:
            return SectionType.TITLE

        return SectionType.OTHER

    def _extract_references_from_docling(self, doc) -> list[ParsedReference]:
        """Extract references from Docling document.

        Args:
            doc: Docling document

        Returns:
            List of parsed references
        """
        references = []
        ref_num = 1

        try:
            # Check if document has bibliography items
            for item in doc.iterate_items():
                item_type = getattr(item, "label", None)
                if item_type and "reference" in str(item_type).lower():
                    text = getattr(item, "text", "") or ""
                    if text.strip():
                        ref = self._parse_reference_text(text, ref_num)
                        references.append(ref)
                        ref_num += 1
        except Exception as e:
            logger.warning("docling_reference_extraction_error", error=str(e))

        return references

    def _parse_reference_text(self, text: str, ref_num: int) -> ParsedReference:
        """Parse reference text to extract metadata.

        Args:
            text: Raw reference text
            ref_num: Reference number

        Returns:
            Parsed reference
        """
        # Extract DOI if present
        doi = None
        doi_match = re.search(r"10\.\d{4,}/[^\s]+", text)
        if doi_match:
            doi = doi_match.group(0).rstrip(".")

        # Extract year
        year = None
        year_match = re.search(r"\b(19|20)\d{2}\b", text)
        if year_match:
            year = int(year_match.group(0))

        # Extract arXiv ID
        arxiv_id = None
        arxiv_match = re.search(r"arXiv:(\d{4}\.\d{4,5})", text, re.IGNORECASE)
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)

        return ParsedReference(
            reference_number=ref_num,
            raw_text=text,
            title=None,  # Would need NLP to extract reliably
            authors=[],  # Would need NLP to extract reliably
            year=year,
            journal=None,
            doi=doi,
            arxiv_id=arxiv_id,
        )

    def _get_page_count_from_docling(self, doc) -> int:
        """Get page count from Docling document.

        Args:
            doc: Docling document

        Returns:
            Page count
        """
        try:
            # Try to get page count from document properties
            if hasattr(doc, "pages"):
                return len(doc.pages)
            if hasattr(doc, "page_count"):
                return doc.page_count
        except Exception:
            pass
        return 1

    def _extract_metadata_from_docling(
        self,
        doc,
        file_type: FileType,
    ) -> dict[str, Any]:
        """Extract metadata from Docling document.

        Args:
            doc: Docling document
            file_type: Source file type

        Returns:
            Metadata dict
        """
        metadata: dict[str, Any] = {
            "parser": "docling",
            "file_type": file_type.value,
        }

        try:
            # Extract title
            if hasattr(doc, "title") and doc.title:
                metadata["title"] = doc.title

            # Extract other metadata properties
            if hasattr(doc, "properties"):
                props = doc.properties
                if hasattr(props, "author") and props.author:
                    metadata["authors"] = [props.author] if isinstance(props.author, str) else props.author
                if hasattr(props, "created") and props.created:
                    metadata["created"] = str(props.created)

        except Exception as e:
            logger.warning("docling_metadata_extraction_error", error=str(e))

        return metadata

    async def _fallback_parse(
        self,
        content: bytes,
        file_type: FileType,
    ) -> ExtractedText:
        """Fallback parsing when Docling is unavailable.

        Args:
            content: Document bytes
            file_type: File type

        Returns:
            Basic extracted text
        """
        if file_type == FileType.PDF:
            return await self._fallback_parse_pdf(content)

        # For other formats, return empty result with error
        return ExtractedText(
            full_text="",
            sections=[],
            references=[],
            page_count=0,
            metadata={
                "error": f"Cannot parse {file_type.value} without Docling installed",
                "file_type": file_type.value,
            },
        )

    async def _fallback_parse_pdf(self, content: bytes) -> ExtractedText:
        """Fallback PDF parsing using PyMuPDF.

        Args:
            content: PDF bytes

        Returns:
            Basic extracted text
        """
        try:
            import fitz

            doc = fitz.open(stream=content, filetype="pdf")
            pages_text = []

            for page in doc:
                text = page.get_text()
                pages_text.append(text)

            full_text = "\n\n".join(pages_text)
            doc.close()

            return ExtractedText(
                full_text=full_text,
                sections=[
                    ParsedSection(
                        section_type=SectionType.OTHER,
                        title=None,
                        text=full_text,
                        char_offset_start=0,
                        char_offset_end=len(full_text),
                    )
                ],
                references=[],
                page_count=len(pages_text),
                metadata={"parser": "pymupdf_fallback"},
            )

        except ImportError:
            logger.warning("pymupdf_not_available")
            return ExtractedText(
                full_text="",
                sections=[],
                references=[],
                page_count=0,
                metadata={"error": "PDF parsing unavailable"},
            )

    async def parse_pdf(self, pdf_content: bytes) -> ExtractedText:
        """Parse PDF - compatibility method matching GrobidParser interface.

        Args:
            pdf_content: PDF file bytes

        Returns:
            Extracted text with sections and references
        """
        return await self.parse(pdf_content, filename="document.pdf", file_type=FileType.PDF)

    async def check_health(self) -> bool:
        """Check if Docling is available.

        Returns:
            True if Docling is available
        """
        try:
            from docling.document_converter import DocumentConverter

            return True
        except ImportError:
            return False
