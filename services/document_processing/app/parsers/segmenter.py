"""Section segmentation for scientific documents."""

import json
import re
from typing import Any

from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedSection,
    SectionType,
)
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SectionSegmenter:
    """Segment documents into logical sections."""

    # Patterns for detecting section headers
    SECTION_PATTERNS = [
        # Numbered sections: "1. Introduction", "2.1 Methods"
        (r"^(\d+\.?\d*\.?)\s+(.+)$", None),
        # Roman numerals: "I. Introduction", "II. Methods"
        (r"^([IVX]+\.?)\s+(.+)$", None),
        # All caps headers
        (r"^([A-Z][A-Z\s]{3,})$", None),
    ]

    # Keywords for section classification
    SECTION_KEYWORDS = {
        SectionType.ABSTRACT: ["abstract", "summary", "synopsis"],
        SectionType.INTRODUCTION: ["introduction", "background", "motivation", "overview"],
        SectionType.METHODS: [
            "method", "methodology", "approach", "procedure",
            "material", "data", "observation", "instrument",
            "experimental", "technique", "implementation",
        ],
        SectionType.RESULTS: [
            "result", "finding", "outcome", "analysis",
            "measurement", "observation",
        ],
        SectionType.DISCUSSION: ["discussion", "interpretation", "implication"],
        SectionType.CONCLUSION: ["conclusion", "concluding", "summary", "future work"],
        SectionType.REFERENCES: ["reference", "bibliography", "citation"],
        SectionType.ACKNOWLEDGMENTS: ["acknowledgment", "acknowledgement", "thank"],
        SectionType.APPENDIX: ["appendix", "supplement", "supporting information"],
    }

    def segment(self, extracted: ExtractedText) -> list[ParsedSection]:
        """Segment extracted text into sections.

        If GROBID already provided sections, enhance classification.
        Otherwise, perform rule-based segmentation.

        Args:
            extracted: Extracted text from PDF

        Returns:
            List of classified sections
        """
        if extracted.sections and len(extracted.sections) > 1:
            # GROBID provided sections, enhance classification
            return self._enhance_sections(extracted.sections)

        # Perform rule-based segmentation
        return self._rule_based_segment(extracted.full_text)

    def _enhance_sections(self, sections: list[ParsedSection]) -> list[ParsedSection]:
        """Enhance section classification from GROBID.

        Args:
            sections: Sections from GROBID

        Returns:
            Enhanced sections
        """
        enhanced = []

        for section in sections:
            # Re-classify if needed
            if section.section_type == SectionType.OTHER and section.title:
                new_type = self._classify_by_title(section.title)
                section = ParsedSection(
                    section_type=new_type,
                    title=section.title,
                    text=section.text,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    char_offset_start=section.char_offset_start,
                    char_offset_end=section.char_offset_end,
                )

            enhanced.append(section)

        return enhanced

    def _rule_based_segment(self, text: str) -> list[ParsedSection]:
        """Perform rule-based segmentation.

        Args:
            text: Full document text

        Returns:
            List of sections
        """
        sections = []
        lines = text.split("\n")

        current_section = None
        current_text_lines = []
        char_offset = 0

        for line in lines:
            line_stripped = line.strip()

            # Check if this line is a section header
            header_match = self._match_header(line_stripped)

            if header_match:
                # Save previous section
                if current_text_lines:
                    section_text = "\n".join(current_text_lines)
                    sections.append(ParsedSection(
                        section_type=current_section or SectionType.OTHER,
                        title=current_section.value if current_section else None,
                        text=section_text,
                        char_offset_start=char_offset - len(section_text) - 1,
                        char_offset_end=char_offset - 1,
                    ))

                # Start new section
                current_section = self._classify_by_title(header_match)
                current_text_lines = []
            else:
                # Add to current section
                if line_stripped:
                    current_text_lines.append(line_stripped)

            char_offset += len(line) + 1  # +1 for newline

        # Save final section
        if current_text_lines:
            section_text = "\n".join(current_text_lines)
            sections.append(ParsedSection(
                section_type=current_section or SectionType.OTHER,
                title=current_section.value if current_section else None,
                text=section_text,
                char_offset_start=char_offset - len(section_text) - 1,
                char_offset_end=char_offset - 1,
            ))

        # If no sections found, create single OTHER section
        if not sections:
            sections.append(ParsedSection(
                section_type=SectionType.OTHER,
                title=None,
                text=text,
                char_offset_start=0,
                char_offset_end=len(text),
            ))

        return sections

    def _match_header(self, line: str) -> str | None:
        """Check if line matches a section header pattern.

        Args:
            line: Line text

        Returns:
            Header title if matched, None otherwise
        """
        if not line or len(line) > 100:  # Headers are typically short
            return None

        # Check patterns
        for pattern, _ in self.SECTION_PATTERNS:
            match = re.match(pattern, line, re.IGNORECASE)
            if match:
                # Return the actual title part
                groups = match.groups()
                return groups[-1] if len(groups) > 1 else groups[0]

        # Check if all caps (potential header)
        if line.isupper() and len(line) > 3:
            return line

        return None

    def _classify_by_title(self, title: str) -> SectionType:
        """Classify section type by title.

        Args:
            title: Section title

        Returns:
            Section type
        """
        title_lower = title.lower()

        for section_type, keywords in self.SECTION_KEYWORDS.items():
            for keyword in keywords:
                if keyword in title_lower:
                    return section_type

        return SectionType.OTHER

    def create_structure_map(self, sections: list[ParsedSection]) -> str:
        """Create a JSON structure map of the document.

        Args:
            sections: Document sections

        Returns:
            JSON string of structure map
        """
        structure = {
            "sections": [
                {
                    "type": s.section_type.value,
                    "title": s.title,
                    "char_offset_start": s.char_offset_start,
                    "char_offset_end": s.char_offset_end,
                    "length": s.char_offset_end - s.char_offset_start,
                }
                for s in sections
            ],
            "total_sections": len(sections),
            "section_types": list(set(s.section_type.value for s in sections)),
        }

        return json.dumps(structure, indent=2)

    def get_section_by_offset(
        self,
        sections: list[ParsedSection],
        char_offset: int,
    ) -> ParsedSection | None:
        """Get section containing a character offset.

        Args:
            sections: Document sections
            char_offset: Character offset

        Returns:
            Section containing the offset, or None
        """
        for section in sections:
            if section.char_offset_start <= char_offset < section.char_offset_end:
                return section
        return None

    def merge_short_sections(
        self,
        sections: list[ParsedSection],
        min_length: int = 100,
    ) -> list[ParsedSection]:
        """Merge sections that are too short.

        Args:
            sections: Document sections
            min_length: Minimum section length

        Returns:
            Merged sections
        """
        if not sections:
            return sections

        merged = []
        current = sections[0]

        for section in sections[1:]:
            # If current section is too short, merge with next
            if len(current.text) < min_length:
                # Merge texts
                merged_text = current.text + "\n\n" + section.text
                current = ParsedSection(
                    section_type=section.section_type,  # Use next section's type
                    title=section.title or current.title,
                    text=merged_text,
                    page_start=current.page_start,
                    page_end=section.page_end,
                    char_offset_start=current.char_offset_start,
                    char_offset_end=section.char_offset_end,
                )
            else:
                merged.append(current)
                current = section

        # Add final section
        merged.append(current)

        return merged
