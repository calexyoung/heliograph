"""Tests for section segmentation."""

import pytest

from services.document_processing.app.core.schemas import (
    ExtractedText,
    ParsedSection,
    SectionType,
)
from services.document_processing.app.parsers.segmenter import SectionSegmenter


class TestSectionSegmenter:
    """Tests for section segmenter."""

    @pytest.fixture
    def segmenter(self):
        """Create segmenter instance."""
        return SectionSegmenter()

    def test_classify_introduction(self, segmenter):
        """Test classification of introduction section."""
        section_type = segmenter._classify_by_title("Introduction")
        assert section_type == SectionType.INTRODUCTION

        section_type = segmenter._classify_by_title("1. Introduction")
        assert section_type == SectionType.INTRODUCTION

        section_type = segmenter._classify_by_title("Background and Motivation")
        assert section_type == SectionType.INTRODUCTION

    def test_classify_methods(self, segmenter):
        """Test classification of methods section."""
        section_type = segmenter._classify_by_title("Methods")
        assert section_type == SectionType.METHODS

        section_type = segmenter._classify_by_title("Materials and Methods")
        assert section_type == SectionType.METHODS

        section_type = segmenter._classify_by_title("Data and Observations")
        assert section_type == SectionType.METHODS

        section_type = segmenter._classify_by_title("Instrumentation")
        assert section_type == SectionType.METHODS

    def test_classify_results(self, segmenter):
        """Test classification of results section."""
        section_type = segmenter._classify_by_title("Results")
        assert section_type == SectionType.RESULTS

        section_type = segmenter._classify_by_title("Results and Analysis")
        assert section_type == SectionType.RESULTS

        section_type = segmenter._classify_by_title("Findings")
        assert section_type == SectionType.RESULTS

    def test_classify_discussion(self, segmenter):
        """Test classification of discussion section."""
        section_type = segmenter._classify_by_title("Discussion")
        assert section_type == SectionType.DISCUSSION

    def test_classify_conclusion(self, segmenter):
        """Test classification of conclusion section."""
        section_type = segmenter._classify_by_title("Conclusion")
        assert section_type == SectionType.CONCLUSION

        section_type = segmenter._classify_by_title("Conclusions and Future Work")
        assert section_type == SectionType.CONCLUSION

    def test_classify_references(self, segmenter):
        """Test classification of references section."""
        section_type = segmenter._classify_by_title("References")
        assert section_type == SectionType.REFERENCES

        section_type = segmenter._classify_by_title("Bibliography")
        assert section_type == SectionType.REFERENCES

    def test_classify_unknown(self, segmenter):
        """Test classification of unknown section."""
        section_type = segmenter._classify_by_title("Random Section Title")
        assert section_type == SectionType.OTHER

    def test_enhance_sections(self, segmenter):
        """Test enhancement of GROBID sections."""
        sections = [
            ParsedSection(
                section_type=SectionType.OTHER,
                title="Introduction",
                text="This is the introduction.",
                char_offset_start=0,
                char_offset_end=25,
            ),
            ParsedSection(
                section_type=SectionType.OTHER,
                title="Methods",
                text="These are the methods.",
                char_offset_start=27,
                char_offset_end=49,
            ),
        ]

        enhanced = segmenter._enhance_sections(sections)

        assert enhanced[0].section_type == SectionType.INTRODUCTION
        assert enhanced[1].section_type == SectionType.METHODS

    def test_segment_extracted_text(self, segmenter, sample_extracted_text):
        """Test segmentation of extracted text."""
        sections = segmenter.segment(sample_extracted_text)

        assert len(sections) == len(sample_extracted_text.sections)

    def test_rule_based_segment(self, segmenter):
        """Test rule-based segmentation."""
        text = """ABSTRACT

This is the abstract.

1. INTRODUCTION

This is the introduction.

2. METHODS

This is the methods section.
"""
        sections = segmenter._rule_based_segment(text)

        # Should find multiple sections
        assert len(sections) >= 1

    def test_match_header_numbered(self, segmenter):
        """Test header matching for numbered sections."""
        assert segmenter._match_header("1. Introduction") is not None
        assert segmenter._match_header("2.1 Methods") is not None
        assert segmenter._match_header("This is regular text.") is None

    def test_match_header_caps(self, segmenter):
        """Test header matching for all-caps sections."""
        assert segmenter._match_header("INTRODUCTION") is not None
        assert segmenter._match_header("METHODS AND MATERIALS") is not None
        assert segmenter._match_header("ABC") is None  # Too short

    def test_create_structure_map(self, segmenter, sample_extracted_text):
        """Test structure map creation."""
        structure_json = segmenter.create_structure_map(sample_extracted_text.sections)

        import json
        structure = json.loads(structure_json)

        assert "sections" in structure
        assert "total_sections" in structure
        assert structure["total_sections"] == len(sample_extracted_text.sections)

    def test_get_section_by_offset(self, segmenter, sample_extracted_text):
        """Test finding section by character offset."""
        sections = sample_extracted_text.sections

        # Find section at offset in abstract
        section = segmenter.get_section_by_offset(sections, 50)
        assert section is not None
        assert section.section_type == SectionType.ABSTRACT

    def test_merge_short_sections(self, segmenter):
        """Test merging of short sections."""
        sections = [
            ParsedSection(
                section_type=SectionType.OTHER,
                title="Short",
                text="Short text.",
                char_offset_start=0,
                char_offset_end=11,
            ),
            ParsedSection(
                section_type=SectionType.INTRODUCTION,
                title="Introduction",
                text="This is a longer introduction section with more content.",
                char_offset_start=13,
                char_offset_end=69,
            ),
        ]

        merged = segmenter.merge_short_sections(sections, min_length=50)

        # Short section should be merged into introduction
        assert len(merged) < len(sections)
