"""GROBID PDF parsing client."""

import re
from typing import Any
from xml.etree import ElementTree

import httpx

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedReference,
    ParsedSection,
    SectionType,
)
from shared.utils.logging import get_logger

logger = get_logger(__name__)

# TEI XML namespaces
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


class GrobidParser:
    """Client for GROBID PDF parsing service."""

    def __init__(self, grobid_url: str = None, timeout: int = None):
        """Initialize GROBID parser.

        Args:
            grobid_url: GROBID service URL
            timeout: Request timeout in seconds
        """
        self.grobid_url = (grobid_url or settings.GROBID_URL).rstrip("/")
        self.timeout = timeout or settings.GROBID_TIMEOUT

    async def parse_pdf(self, pdf_content: bytes) -> ExtractedText:
        """Parse PDF using GROBID.

        Args:
            pdf_content: PDF file bytes

        Returns:
            Extracted text with sections and references
        """
        try:
            # Call GROBID processFulltextDocument
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.grobid_url}/api/processFulltextDocument",
                    files={"input": ("document.pdf", pdf_content, "application/pdf")},
                    data={
                        "consolidateHeader": "1",
                        "consolidateCitations": "1",
                        "includeRawCitations": "1",
                        "teiCoordinates": "figure,ref,biblStruct",
                    },
                )
                response.raise_for_status()
                tei_xml = response.text

            # Parse TEI XML
            return self._parse_tei(tei_xml)

        except httpx.HTTPStatusError as e:
            logger.error("grobid_http_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("grobid_parse_error", error=str(e))
            # Fall back to basic extraction
            return await self._fallback_parse(pdf_content)

    def _parse_tei(self, tei_xml: str) -> ExtractedText:
        """Parse GROBID TEI XML output.

        Args:
            tei_xml: TEI XML string

        Returns:
            Extracted text structure
        """
        root = ElementTree.fromstring(tei_xml)

        # Extract sections
        sections = self._extract_sections(root)

        # Extract references
        references = self._extract_references(root)

        # Get full text
        full_text = "\n\n".join(s.text for s in sections)

        # Get page count from TEI if available
        page_count = self._get_page_count(root)

        # Extract metadata
        metadata = self._extract_metadata(root)

        return ExtractedText(
            full_text=full_text,
            sections=sections,
            references=references,
            page_count=page_count,
            metadata=metadata,
        )

    def _extract_sections(self, root: ElementTree.Element) -> list[ParsedSection]:
        """Extract sections from TEI.

        Args:
            root: TEI root element

        Returns:
            List of parsed sections
        """
        sections = []
        char_offset = 0

        # Extract abstract
        abstract = root.find(".//tei:abstract", TEI_NS)
        if abstract is not None:
            abstract_text = self._get_element_text(abstract)
            if abstract_text:
                sections.append(ParsedSection(
                    section_type=SectionType.ABSTRACT,
                    title="Abstract",
                    text=abstract_text,
                    char_offset_start=char_offset,
                    char_offset_end=char_offset + len(abstract_text),
                ))
                char_offset += len(abstract_text) + 2  # +2 for newlines

        # Extract body sections
        body = root.find(".//tei:body", TEI_NS)
        if body is not None:
            for div in body.findall(".//tei:div", TEI_NS):
                section = self._parse_div(div, char_offset)
                if section:
                    sections.append(section)
                    char_offset = section.char_offset_end + 2

        # Extract back matter (references section)
        back = root.find(".//tei:back", TEI_NS)
        if back is not None:
            refs_div = back.find(".//tei:div[@type='references']", TEI_NS)
            if refs_div is not None:
                refs_text = self._get_element_text(refs_div)
                if refs_text:
                    sections.append(ParsedSection(
                        section_type=SectionType.REFERENCES,
                        title="References",
                        text=refs_text,
                        char_offset_start=char_offset,
                        char_offset_end=char_offset + len(refs_text),
                    ))

        return sections

    def _parse_div(self, div: ElementTree.Element, char_offset: int) -> ParsedSection | None:
        """Parse a TEI div element into a section.

        Args:
            div: TEI div element
            char_offset: Current character offset

        Returns:
            Parsed section or None
        """
        # Get section heading
        head = div.find("tei:head", TEI_NS)
        title = head.text.strip() if head is not None and head.text else None

        # Get section text
        text = self._get_element_text(div)
        if not text:
            return None

        # Classify section type
        section_type = self._classify_section(title, text)

        return ParsedSection(
            section_type=section_type,
            title=title,
            text=text,
            char_offset_start=char_offset,
            char_offset_end=char_offset + len(text),
        )

    def _classify_section(self, title: str | None, text: str) -> SectionType:
        """Classify section type from title.

        Args:
            title: Section title
            text: Section text (for fallback classification)

        Returns:
            Section type
        """
        if not title:
            return SectionType.OTHER

        title_lower = title.lower().strip()

        # Check common section names
        if any(kw in title_lower for kw in ["abstract", "summary"]):
            return SectionType.ABSTRACT
        if any(kw in title_lower for kw in ["introduction", "background"]):
            return SectionType.INTRODUCTION
        if any(kw in title_lower for kw in ["method", "material", "data", "observation", "instrument"]):
            return SectionType.METHODS
        if any(kw in title_lower for kw in ["result", "finding", "analysis"]):
            return SectionType.RESULTS
        if any(kw in title_lower for kw in ["discussion"]):
            return SectionType.DISCUSSION
        if any(kw in title_lower for kw in ["conclusion", "concluding"]):
            return SectionType.CONCLUSION
        if any(kw in title_lower for kw in ["reference", "bibliography"]):
            return SectionType.REFERENCES
        if any(kw in title_lower for kw in ["acknowledgment", "acknowledgement"]):
            return SectionType.ACKNOWLEDGMENTS
        if any(kw in title_lower for kw in ["appendix", "supplement"]):
            return SectionType.APPENDIX

        return SectionType.OTHER

    def _extract_references(self, root: ElementTree.Element) -> list[ParsedReference]:
        """Extract references from TEI.

        Args:
            root: TEI root element

        Returns:
            List of parsed references
        """
        references = []

        # Find all biblStruct elements
        for i, bibl in enumerate(root.findall(".//tei:listBibl/tei:biblStruct", TEI_NS), 1):
            ref = self._parse_bibl_struct(bibl, i)
            if ref:
                references.append(ref)

        return references

    def _parse_bibl_struct(
        self,
        bibl: ElementTree.Element,
        ref_num: int,
    ) -> ParsedReference | None:
        """Parse a biblStruct element.

        Args:
            bibl: biblStruct element
            ref_num: Reference number

        Returns:
            Parsed reference
        """
        # Get raw text
        raw_text = self._get_element_text(bibl)

        # Extract title
        title_elem = bibl.find(".//tei:title[@level='a']", TEI_NS)
        if title_elem is None:
            title_elem = bibl.find(".//tei:title", TEI_NS)
        title = title_elem.text if title_elem is not None and title_elem.text else None

        # Extract authors
        authors = []
        for author in bibl.findall(".//tei:author/tei:persName", TEI_NS):
            forename = author.find("tei:forename", TEI_NS)
            surname = author.find("tei:surname", TEI_NS)
            name_parts = []
            if forename is not None and forename.text:
                name_parts.append(forename.text)
            if surname is not None and surname.text:
                name_parts.append(surname.text)
            if name_parts:
                authors.append(" ".join(name_parts))

        # Extract year
        year = None
        date = bibl.find(".//tei:date", TEI_NS)
        if date is not None:
            when = date.get("when")
            if when:
                year_match = re.match(r"(\d{4})", when)
                if year_match:
                    year = int(year_match.group(1))

        # Extract journal
        journal = None
        journal_elem = bibl.find(".//tei:title[@level='j']", TEI_NS)
        if journal_elem is not None and journal_elem.text:
            journal = journal_elem.text

        # Extract DOI
        doi = None
        idno = bibl.find(".//tei:idno[@type='DOI']", TEI_NS)
        if idno is not None and idno.text:
            doi = idno.text

        # Extract arXiv ID
        arxiv_id = None
        arxiv = bibl.find(".//tei:idno[@type='arXiv']", TEI_NS)
        if arxiv is not None and arxiv.text:
            arxiv_id = arxiv.text

        return ParsedReference(
            reference_number=ref_num,
            raw_text=raw_text,
            title=title,
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
            arxiv_id=arxiv_id,
        )

    def _get_element_text(self, element: ElementTree.Element) -> str:
        """Get all text content from an element.

        Args:
            element: XML element

        Returns:
            Text content
        """
        texts = []
        for text in element.itertext():
            if text.strip():
                texts.append(text.strip())
        return " ".join(texts)

    def _get_page_count(self, root: ElementTree.Element) -> int:
        """Get page count from TEI if available.

        Args:
            root: TEI root element

        Returns:
            Page count (default 1)
        """
        # Try to find page break elements
        page_breaks = root.findall(".//{*}pb")
        if page_breaks:
            return len(page_breaks)

        # Default
        return 1

    def _extract_metadata(self, root: ElementTree.Element) -> dict[str, Any]:
        """Extract document metadata from TEI header.

        Args:
            root: TEI root element

        Returns:
            Metadata dict
        """
        metadata = {}

        # Get title
        title = root.find(".//tei:titleStmt/tei:title", TEI_NS)
        if title is not None and title.text:
            metadata["title"] = title.text

        # Get authors
        authors = []
        for author in root.findall(".//tei:sourceDesc//tei:author", TEI_NS):
            persname = author.find("tei:persName", TEI_NS)
            if persname is not None:
                name = self._get_element_text(persname)
                if name:
                    authors.append(name)
        if authors:
            metadata["authors"] = authors

        # Get publication date
        date = root.find(".//tei:sourceDesc//tei:date", TEI_NS)
        if date is not None:
            when = date.get("when")
            if when:
                metadata["publication_date"] = when

        # Get DOI
        doi = root.find(".//tei:idno[@type='DOI']", TEI_NS)
        if doi is not None and doi.text:
            metadata["doi"] = doi.text

        return metadata

    async def _fallback_parse(self, pdf_content: bytes) -> ExtractedText:
        """Fallback PDF parsing using PyMuPDF.

        Args:
            pdf_content: PDF file bytes

        Returns:
            Basic extracted text
        """
        try:
            import fitz

            doc = fitz.open(stream=pdf_content, filetype="pdf")
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
                metadata={},
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

    async def check_health(self) -> bool:
        """Check GROBID service health.

        Returns:
            True if service is healthy
        """
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.grobid_url}/api/isalive")
                return response.status_code == 200
        except Exception:
            return False
