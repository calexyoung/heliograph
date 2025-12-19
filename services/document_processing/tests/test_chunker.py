"""Tests for chunking service."""

import uuid
import pytest

from services.document_processing.app.core.schemas import ParsedSection, SectionType
from services.document_processing.app.parsers.chunker import ChunkingService


class TestChunkingService:
    """Tests for chunking service."""

    @pytest.fixture
    def chunker(self):
        """Create chunker instance."""
        return ChunkingService(
            max_tokens=100,
            overlap_tokens=10,
            respect_sections=True,
            min_chunk_tokens=10,
        )

    def test_chunk_single_section(self, chunker):
        """Test chunking a single short section."""
        document_id = uuid.uuid4()
        sections = [
            ParsedSection(
                section_type=SectionType.ABSTRACT,
                title="Abstract",
                text="This is a short abstract about solar physics research.",
                char_offset_start=0,
                char_offset_end=54,
            )
        ]

        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) == 1
        assert chunks[0].section == SectionType.ABSTRACT
        assert chunks[0].sequence_number == 0
        assert "solar physics" in chunks[0].text

    def test_chunk_long_section(self, chunker):
        """Test chunking a long section into multiple chunks."""
        document_id = uuid.uuid4()

        # Create a long section that should be split
        long_text = " ".join(["This is sentence number {}.".format(i) for i in range(50)])

        sections = [
            ParsedSection(
                section_type=SectionType.INTRODUCTION,
                title="Introduction",
                text=long_text,
                char_offset_start=0,
                char_offset_end=len(long_text),
            )
        ]

        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) > 1
        # Check sequence numbers are correct
        for i, chunk in enumerate(chunks):
            assert chunk.sequence_number == i

    def test_skip_references_section(self, chunker):
        """Test that references section is skipped."""
        document_id = uuid.uuid4()
        sections = [
            ParsedSection(
                section_type=SectionType.ABSTRACT,
                title="Abstract",
                text="This is the abstract.",
                char_offset_start=0,
                char_offset_end=21,
            ),
            ParsedSection(
                section_type=SectionType.REFERENCES,
                title="References",
                text="[1] Author A. Paper Title. Journal. 2024.",
                char_offset_start=23,
                char_offset_end=65,
            ),
        ]

        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) == 1
        assert chunks[0].section == SectionType.ABSTRACT

    def test_chunk_metadata(self, chunker):
        """Test that chunk metadata is preserved."""
        document_id = uuid.uuid4()
        sections = [
            ParsedSection(
                section_type=SectionType.METHODS,
                title="Methods and Materials",
                text="We used SDO data for this analysis.",
                page_start=5,
                page_end=5,
                char_offset_start=100,
                char_offset_end=136,
            )
        ]

        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) == 1
        assert chunks[0].page_start == 5
        assert chunks[0].page_end == 5
        assert chunks[0].metadata.get("section_title") == "Methods and Materials"

    def test_tokenize(self, chunker):
        """Test simple tokenization."""
        text = "This is a test sentence."
        tokens = chunker._tokenize(text)

        assert len(tokens) == 5
        assert tokens[0] == "This"
        assert tokens[-1] == "sentence."

    def test_split_sentences(self, chunker):
        """Test sentence splitting."""
        text = "First sentence. Second sentence! Third sentence?"
        sentences = chunker._split_sentences(text)

        assert len(sentences) == 3
        assert "First" in sentences[0]
        assert "Second" in sentences[1]
        assert "Third" in sentences[2]

    def test_estimate_chunks(self, chunker, sample_extracted_text):
        """Test chunk estimation."""
        estimated = chunker.estimate_chunks(sample_extracted_text.sections)

        # Should estimate at least 1 chunk
        assert estimated >= 1

    def test_empty_sections(self, chunker):
        """Test handling of empty sections."""
        document_id = uuid.uuid4()
        sections = [
            ParsedSection(
                section_type=SectionType.OTHER,
                title="Empty",
                text="",
                char_offset_start=0,
                char_offset_end=0,
            )
        ]

        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) == 0
