"""Text chunking for RAG retrieval."""

import re
import uuid
from typing import Any

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import (
    Chunk,
    ChunkingConfig,
    ParsedSection,
    SectionType,
)
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class ChunkingService:
    """Service for chunking documents into retrieval units."""

    def __init__(
        self,
        max_tokens: int = 512,
        overlap_tokens: int = 50,
        respect_sections: bool = True,
        min_chunk_tokens: int = 50,
    ):
        """Initialize chunking service.

        Args:
            max_tokens: Maximum tokens per chunk
            overlap_tokens: Token overlap between chunks
            respect_sections: Whether to avoid crossing section boundaries
            min_chunk_tokens: Minimum tokens for a valid chunk
        """
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens
        self.respect_sections = respect_sections
        self.min_chunk_tokens = min_chunk_tokens

        # Simple tokenizer (word-based approximation)
        # In production, use tiktoken or similar
        self._token_pattern = re.compile(r"\S+")

    def chunk_document(
        self,
        document_id: uuid.UUID,
        sections: list[ParsedSection],
    ) -> list[Chunk]:
        """Chunk a document into retrieval units.

        Args:
            document_id: Document ID
            sections: Document sections

        Returns:
            List of chunks
        """
        chunks = []
        sequence_number = 0

        for section in sections:
            # Skip empty sections
            if not section.text.strip():
                continue

            # Skip references section (usually not useful for retrieval)
            if section.section_type == SectionType.REFERENCES:
                continue

            # Chunk the section
            section_chunks = self._chunk_section(
                document_id=document_id,
                section=section,
                start_sequence=sequence_number,
            )

            chunks.extend(section_chunks)
            sequence_number += len(section_chunks)

        logger.info(
            "document_chunked",
            document_id=str(document_id),
            chunk_count=len(chunks),
            total_tokens=sum(c.token_count for c in chunks),
        )

        return chunks

    def _chunk_section(
        self,
        document_id: uuid.UUID,
        section: ParsedSection,
        start_sequence: int,
    ) -> list[Chunk]:
        """Chunk a single section.

        Args:
            document_id: Document ID
            section: Section to chunk
            start_sequence: Starting sequence number

        Returns:
            List of chunks from this section
        """
        text = section.text
        tokens = self._tokenize(text)

        if len(tokens) <= self.max_tokens:
            # Section fits in single chunk
            return [
                Chunk(
                    chunk_id=uuid.uuid4(),
                    document_id=document_id,
                    sequence_number=start_sequence,
                    text=text,
                    section=section.section_type,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    char_offset_start=section.char_offset_start,
                    char_offset_end=section.char_offset_end,
                    token_count=len(tokens),
                    metadata={
                        "section_title": section.title,
                    },
                )
            ]

        # Split into multiple chunks
        chunks = []
        sequence = start_sequence

        # Try to split on sentence boundaries
        sentences = self._split_sentences(text)

        current_text = ""
        current_tokens = 0
        current_start = section.char_offset_start

        for sentence in sentences:
            sentence_tokens = len(self._tokenize(sentence))

            if current_tokens + sentence_tokens > self.max_tokens:
                # Save current chunk if it has content
                if current_text and current_tokens >= self.min_chunk_tokens:
                    chunks.append(
                        Chunk(
                            chunk_id=uuid.uuid4(),
                            document_id=document_id,
                            sequence_number=sequence,
                            text=current_text.strip(),
                            section=section.section_type,
                            page_start=section.page_start,
                            page_end=section.page_end,
                            char_offset_start=current_start,
                            char_offset_end=current_start + len(current_text),
                            token_count=current_tokens,
                            metadata={
                                "section_title": section.title,
                            },
                        )
                    )
                    sequence += 1

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_text)
                current_text = overlap_text + sentence
                current_tokens = len(self._tokenize(current_text))
                current_start = section.char_offset_start + (
                    section.char_offset_end - section.char_offset_start
                ) - len(current_text)
            else:
                current_text += sentence
                current_tokens += sentence_tokens

        # Save final chunk
        if current_text and current_tokens >= self.min_chunk_tokens:
            chunks.append(
                Chunk(
                    chunk_id=uuid.uuid4(),
                    document_id=document_id,
                    sequence_number=sequence,
                    text=current_text.strip(),
                    section=section.section_type,
                    page_start=section.page_start,
                    page_end=section.page_end,
                    char_offset_start=current_start,
                    char_offset_end=section.char_offset_end,
                    token_count=current_tokens,
                    metadata={
                        "section_title": section.title,
                    },
                )
            )

        return chunks

    def _tokenize(self, text: str) -> list[str]:
        """Simple word tokenization.

        Args:
            text: Text to tokenize

        Returns:
            List of tokens
        """
        return self._token_pattern.findall(text)

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        # Simple sentence splitting
        # In production, use spacy or nltk
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s for s in sentences if s.strip()]

    def _get_overlap_text(self, text: str) -> str:
        """Get overlap text from end of chunk.

        Args:
            text: Current chunk text

        Returns:
            Overlap text
        """
        if not text:
            return ""

        tokens = self._tokenize(text)
        if len(tokens) <= self.overlap_tokens:
            return text

        # Get last N tokens worth of text
        overlap_tokens = tokens[-self.overlap_tokens:]
        overlap_text = " ".join(overlap_tokens)

        return overlap_text + " "

    def estimate_chunks(
        self,
        sections: list[ParsedSection],
    ) -> int:
        """Estimate number of chunks for a document.

        Args:
            sections: Document sections

        Returns:
            Estimated chunk count
        """
        total_tokens = 0

        for section in sections:
            if section.section_type != SectionType.REFERENCES:
                total_tokens += len(self._tokenize(section.text))

        # Account for overlap
        effective_chunk_size = self.max_tokens - self.overlap_tokens
        estimated = max(1, total_tokens // effective_chunk_size)

        return estimated


class SemanticChunker:
    """Semantic-aware chunking using embeddings.

    For future use - chunks based on semantic similarity
    rather than fixed token counts.
    """

    def __init__(
        self,
        embedding_model: Any = None,
        similarity_threshold: float = 0.8,
        max_tokens: int = 512,
    ):
        """Initialize semantic chunker.

        Args:
            embedding_model: Model for generating embeddings
            similarity_threshold: Threshold for merging chunks
            max_tokens: Maximum tokens per chunk
        """
        self.embedding_model = embedding_model
        self.similarity_threshold = similarity_threshold
        self.max_tokens = max_tokens

    async def chunk_semantic(
        self,
        document_id: uuid.UUID,
        text: str,
        section: SectionType | None = None,
    ) -> list[Chunk]:
        """Chunk text using semantic similarity.

        Not implemented yet - placeholder for future enhancement.

        Args:
            document_id: Document ID
            text: Text to chunk
            section: Section type

        Returns:
            List of semantically coherent chunks
        """
        # TODO: Implement semantic chunking
        # 1. Split into sentences
        # 2. Generate sentence embeddings
        # 3. Group sentences by similarity
        # 4. Merge groups up to max_tokens
        raise NotImplementedError("Semantic chunking not yet implemented")
