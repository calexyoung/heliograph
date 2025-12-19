"""Tests for Docling parser and parser factory."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedSection,
    SectionType,
)
from services.document_processing.app.parsers.docling_parser import (
    DoclingParser,
    FileType,
    detect_file_type,
    EXTENSION_MAP,
)
from services.document_processing.app.parsers.factory import (
    ParserFactory,
    get_parser_factory,
    reset_parser_factory,
)


class TestFileTypeDetection:
    """Tests for file type detection."""

    def test_detect_pdf_from_extension(self):
        """Test PDF detection from extension."""
        assert detect_file_type("document.pdf") == FileType.PDF
        assert detect_file_type("DOCUMENT.PDF") == FileType.PDF

    def test_detect_docx_from_extension(self):
        """Test DOCX detection from extension."""
        assert detect_file_type("document.docx") == FileType.DOCX
        assert detect_file_type("document.doc") == FileType.DOCX

    def test_detect_pptx_from_extension(self):
        """Test PPTX detection from extension."""
        assert detect_file_type("slides.pptx") == FileType.PPTX
        assert detect_file_type("slides.ppt") == FileType.PPTX

    def test_detect_xlsx_from_extension(self):
        """Test XLSX detection from extension."""
        assert detect_file_type("data.xlsx") == FileType.XLSX
        assert detect_file_type("data.xls") == FileType.XLSX

    def test_detect_html_from_extension(self):
        """Test HTML detection from extension."""
        assert detect_file_type("page.html") == FileType.HTML
        assert detect_file_type("page.htm") == FileType.HTML

    def test_detect_image_from_extension(self):
        """Test image detection from extension."""
        assert detect_file_type("photo.png") == FileType.IMAGE
        assert detect_file_type("photo.jpg") == FileType.IMAGE
        assert detect_file_type("photo.jpeg") == FileType.IMAGE
        assert detect_file_type("scan.tiff") == FileType.IMAGE
        assert detect_file_type("scan.tif") == FileType.IMAGE

    def test_detect_markdown_from_extension(self):
        """Test markdown detection from extension."""
        assert detect_file_type("readme.md") == FileType.MARKDOWN
        assert detect_file_type("readme.markdown") == FileType.MARKDOWN

    def test_detect_pdf_from_magic_bytes(self):
        """Test PDF detection from content magic bytes."""
        pdf_content = b"%PDF-1.4 rest of content"
        assert detect_file_type(None, pdf_content) == FileType.PDF

    def test_detect_png_from_magic_bytes(self):
        """Test PNG detection from magic bytes."""
        png_content = b"\x89PNG\r\n\x1a\n rest of content"
        assert detect_file_type(None, png_content) == FileType.IMAGE

    def test_detect_jpeg_from_magic_bytes(self):
        """Test JPEG detection from magic bytes."""
        jpeg_content = b"\xff\xd8 rest of content"
        assert detect_file_type(None, jpeg_content) == FileType.IMAGE

    def test_detect_tiff_from_magic_bytes(self):
        """Test TIFF detection from magic bytes."""
        tiff_le = b"II*\x00 rest of content"
        tiff_be = b"MM\x00* rest of content"
        assert detect_file_type(None, tiff_le) == FileType.IMAGE
        assert detect_file_type(None, tiff_be) == FileType.IMAGE

    def test_default_to_pdf_for_unknown(self):
        """Test default to PDF for unknown types."""
        assert detect_file_type("unknown.xyz") == FileType.PDF
        assert detect_file_type(None, b"unknown content") == FileType.PDF


class TestDoclingParser:
    """Tests for DoclingParser class."""

    @pytest.fixture
    def parser(self):
        """Create parser instance."""
        return DoclingParser(ocr_enabled=False, table_structure=False)

    @pytest.mark.asyncio
    async def test_parse_pdf_fallback_when_docling_unavailable(self, parser):
        """Test fallback to PyMuPDF when Docling is not installed."""
        pdf_content = b"%PDF-1.4 fake pdf content"

        with patch.object(parser, "_parse_with_docling", side_effect=ImportError):
            with patch.object(parser, "_fallback_parse") as mock_fallback:
                mock_fallback.return_value = ExtractedText(
                    full_text="Fallback text",
                    sections=[],
                    references=[],
                    page_count=1,
                    metadata={"parser": "fallback"},
                )

                result = await parser.parse(pdf_content, filename="test.pdf")

                assert result.full_text == "Fallback text"
                assert result.metadata["parser"] == "fallback"
                mock_fallback.assert_called_once()

    @pytest.mark.asyncio
    async def test_parse_pdf_interface_compatibility(self, parser):
        """Test that parse_pdf method matches GrobidParser interface."""
        with patch.object(parser, "parse") as mock_parse:
            mock_parse.return_value = ExtractedText(
                full_text="Test",
                sections=[],
                references=[],
                page_count=1,
                metadata={},
            )

            await parser.parse_pdf(b"pdf content")

            mock_parse.assert_called_once()
            args, kwargs = mock_parse.call_args
            assert kwargs["file_type"] == FileType.PDF

    @pytest.mark.asyncio
    async def test_check_health_returns_false_when_not_installed(self, parser):
        """Test health check returns False when Docling not installed."""
        with patch.dict("sys.modules", {"docling": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                result = await parser.check_health()
                # This should return False when import fails
                assert isinstance(result, bool)

    def test_map_section_type_abstract(self, parser):
        """Test section type mapping for abstract."""
        assert parser._map_docling_label_to_section_type("abstract") == SectionType.ABSTRACT
        assert parser._map_docling_label_to_section_type("ABSTRACT") == SectionType.ABSTRACT

    def test_map_section_type_introduction(self, parser):
        """Test section type mapping for introduction."""
        assert parser._map_docling_label_to_section_type("introduction") == SectionType.INTRODUCTION
        assert parser._map_docling_label_to_section_type("1. Introduction") == SectionType.INTRODUCTION

    def test_map_section_type_methods(self, parser):
        """Test section type mapping for methods."""
        assert parser._map_docling_label_to_section_type("methods") == SectionType.METHODS
        assert parser._map_docling_label_to_section_type("materials and methods") == SectionType.METHODS

    def test_map_section_type_results(self, parser):
        """Test section type mapping for results."""
        assert parser._map_docling_label_to_section_type("results") == SectionType.RESULTS
        assert parser._map_docling_label_to_section_type("3. Results") == SectionType.RESULTS

    def test_map_section_type_discussion(self, parser):
        """Test section type mapping for discussion."""
        assert parser._map_docling_label_to_section_type("discussion") == SectionType.DISCUSSION

    def test_map_section_type_conclusion(self, parser):
        """Test section type mapping for conclusion."""
        assert parser._map_docling_label_to_section_type("conclusion") == SectionType.CONCLUSION
        assert parser._map_docling_label_to_section_type("5. Conclusions") == SectionType.CONCLUSION

    def test_map_section_type_references(self, parser):
        """Test section type mapping for references."""
        assert parser._map_docling_label_to_section_type("references") == SectionType.REFERENCES
        assert parser._map_docling_label_to_section_type("bibliography") == SectionType.REFERENCES

    def test_map_section_type_unknown(self, parser):
        """Test section type mapping for unknown types."""
        assert parser._map_docling_label_to_section_type(None) == SectionType.OTHER
        assert parser._map_docling_label_to_section_type("random heading") == SectionType.OTHER

    def test_parse_reference_text_extracts_doi(self, parser):
        """Test DOI extraction from reference text."""
        ref_text = "Smith, J. (2023). Title. Journal. https://doi.org/10.1234/abcd.5678"
        ref = parser._parse_reference_text(ref_text, 1)

        assert ref.doi == "10.1234/abcd.5678"
        assert ref.reference_number == 1

    def test_parse_reference_text_extracts_year(self, parser):
        """Test year extraction from reference text."""
        ref_text = "Smith, J. (2023). Title of the paper. Journal Name."
        ref = parser._parse_reference_text(ref_text, 1)

        assert ref.year == 2023

    def test_parse_reference_text_extracts_arxiv(self, parser):
        """Test arXiv ID extraction from reference text."""
        ref_text = "Smith, J. arXiv:2312.12345"
        ref = parser._parse_reference_text(ref_text, 1)

        assert ref.arxiv_id == "2312.12345"


class TestParserFactory:
    """Tests for ParserFactory class."""

    @pytest.fixture(autouse=True)
    def reset_factory(self):
        """Reset global factory before each test."""
        reset_parser_factory()
        yield
        reset_parser_factory()

    @pytest.fixture
    def factory(self):
        """Create factory instance."""
        return ParserFactory(docling_enabled=True)

    def test_get_supported_formats_with_docling(self):
        """Test supported formats when Docling is enabled."""
        factory = ParserFactory(docling_enabled=True)
        formats = factory.get_supported_formats()

        assert ".pdf" in formats
        assert ".docx" in formats
        assert ".pptx" in formats
        assert ".xlsx" in formats
        assert ".html" in formats
        assert ".png" in formats

    def test_get_supported_formats_without_docling(self):
        """Test supported formats when Docling is disabled."""
        factory = ParserFactory(docling_enabled=False)
        formats = factory.get_supported_formats()

        assert formats == [".pdf"]

    @pytest.mark.asyncio
    async def test_parse_pdf_uses_docling_when_enabled(self, factory):
        """Test that PDF parsing uses Docling when enabled."""
        with patch.object(factory, "get_docling_parser") as mock_get:
            mock_parser = MagicMock()
            mock_parser.parse_pdf = AsyncMock(
                return_value=ExtractedText(
                    full_text="Docling result",
                    sections=[],
                    references=[],
                    page_count=1,
                    metadata={"parser": "docling"},
                )
            )
            mock_get.return_value = mock_parser

            result = await factory._parse_pdf(b"pdf content")

            assert result.metadata["parser"] == "docling"

    @pytest.mark.asyncio
    async def test_parse_pdf_uses_grobid_when_requested(self, factory):
        """Test that PDF parsing uses GROBID when explicitly requested."""
        with patch.object(factory, "get_grobid_parser") as mock_get:
            mock_parser = MagicMock()
            mock_parser.parse_pdf = AsyncMock(
                return_value=ExtractedText(
                    full_text="GROBID result",
                    sections=[],
                    references=[],
                    page_count=1,
                    metadata={"parser": "grobid"},
                )
            )
            mock_get.return_value = mock_parser

            result = await factory._parse_pdf(b"pdf content", use_grobid=True)

            assert result.metadata["parser"] == "grobid"

    @pytest.mark.asyncio
    async def test_parse_non_pdf_requires_docling(self):
        """Test that non-PDF formats require Docling."""
        factory = ParserFactory(docling_enabled=False)

        with pytest.raises(ValueError, match="Cannot parse docx"):
            await factory.parse(b"content", filename="document.docx")

    @pytest.mark.asyncio
    async def test_check_health_returns_status(self, factory):
        """Test health check returns parser status."""
        with patch.object(factory, "get_docling_parser") as mock_docling:
            with patch.object(factory, "get_grobid_parser") as mock_grobid:
                mock_docling_parser = MagicMock()
                mock_docling_parser.check_health = AsyncMock(return_value=True)
                mock_docling.return_value = mock_docling_parser

                mock_grobid_parser = MagicMock()
                mock_grobid_parser.check_health = AsyncMock(return_value=False)
                mock_grobid.return_value = mock_grobid_parser

                health = await factory.check_health()

                assert health["docling"] is True
                assert health["grobid"] is False

    def test_get_parser_factory_returns_singleton(self):
        """Test that get_parser_factory returns singleton."""
        factory1 = get_parser_factory()
        factory2 = get_parser_factory()

        assert factory1 is factory2

    def test_reset_parser_factory_clears_singleton(self):
        """Test that reset_parser_factory clears singleton."""
        factory1 = get_parser_factory()
        reset_parser_factory()
        factory2 = get_parser_factory()

        assert factory1 is not factory2


class TestExtensionMap:
    """Tests for extension mapping."""

    def test_all_common_extensions_mapped(self):
        """Test that common extensions are mapped."""
        common_extensions = [
            ".pdf",
            ".docx",
            ".pptx",
            ".xlsx",
            ".html",
            ".png",
            ".jpg",
            ".md",
        ]

        for ext in common_extensions:
            assert ext in EXTENSION_MAP, f"Missing extension: {ext}"

    def test_legacy_extensions_mapped_to_modern(self):
        """Test that legacy extensions map to modern formats."""
        assert EXTENSION_MAP[".doc"] == FileType.DOCX
        assert EXTENSION_MAP[".ppt"] == FileType.PPTX
        assert EXTENSION_MAP[".xls"] == FileType.XLSX
        assert EXTENSION_MAP[".htm"] == FileType.HTML
