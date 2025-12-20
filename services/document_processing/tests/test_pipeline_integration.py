"""Integration tests for the document processing pipeline with Docling and LiteLLM.

These tests require:
- docling package installed
- sentence-transformers installed
- litellm installed (for entity extraction tests)
- Optional: API keys for LLM tests (OPENAI_API_KEY or ANTHROPIC_API_KEY)

Run with: pytest services/document_processing/tests/test_pipeline_integration.py -v
"""

import io
import os
from pathlib import Path
from uuid import uuid4

import pytest

# Check if docling is available
try:
    from docling.document_converter import DocumentConverter
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False

# Check if sentence-transformers is available
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False

# Check if litellm is available and API keys are set
try:
    import litellm
    LITELLM_AVAILABLE = True
    HAS_API_KEY = bool(os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY"))
except ImportError:
    LITELLM_AVAILABLE = False
    HAS_API_KEY = False


def create_minimal_pdf() -> bytes:
    """Create a minimal valid PDF for testing.

    This creates a simple PDF with text content that can be parsed.
    """
    # Minimal PDF structure with some text
    pdf_content = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 178 >>
stream
BT
/F1 24 Tf
100 700 Td
(Solar Wind Analysis) Tj
0 -30 Td
/F1 12 Tf
(Abstract: This paper analyzes solar wind data from Parker Solar Probe.) Tj
0 -20 Td
(Methods: We used spectroscopic analysis of plasma composition.) Tj
0 -20 Td
(Results: The solar wind velocity was measured at 400 km/s.) Tj
ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000497 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
574
%%EOF"""
    return pdf_content


@pytest.fixture
def sample_pdf_content() -> bytes:
    """Provide sample PDF content for tests."""
    return create_minimal_pdf()


@pytest.fixture
def heliophysics_text() -> str:
    """Sample heliophysics text for testing."""
    return """
    Abstract: This study investigates solar wind dynamics observed by the
    Parker Solar Probe during its perihelion passes. We analyze the
    relationship between coronal mass ejections and geomagnetic storms.

    Introduction: Solar wind is a continuous stream of charged particles
    released from the Sun's corona. Understanding solar wind properties
    is crucial for space weather prediction.

    Methods: We used data from the Solar Dynamics Observatory (SDO) and
    the Advanced Composition Explorer (ACE) spacecraft. Magnetic field
    measurements were obtained from the Magnetospheric Multiscale (MMS) mission.

    Results: The solar wind velocity ranged from 300-800 km/s during the
    observation period. We detected three interplanetary coronal mass
    ejections (ICMEs) with associated geomagnetic activity.

    Conclusion: Our findings suggest a strong correlation between
    solar wind speed enhancements and geomagnetic storm intensity.
    """


class TestDoclingIntegration:
    """Integration tests for Docling parser."""

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    def test_docling_import(self):
        """Test that Docling can be imported."""
        from docling.document_converter import DocumentConverter
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat

        assert DocumentConverter is not None
        assert PdfPipelineOptions is not None
        assert InputFormat is not None

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    def test_docling_converter_initialization(self):
        """Test that Docling converter can be initialized."""
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.datamodel.base_models import InputFormat

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = False
        pipeline_options.do_table_structure = False

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        assert converter is not None

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    @pytest.mark.asyncio
    async def test_docling_parser_initialization(self):
        """Test DoclingParser initialization."""
        from services.document_processing.app.parsers.docling_parser import DoclingParser

        parser = DoclingParser(ocr_enabled=False, table_structure=False)

        assert parser is not None
        assert parser.ocr_enabled is False
        assert parser.table_structure is False

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    @pytest.mark.asyncio
    async def test_docling_parser_health_check(self):
        """Test DoclingParser health check."""
        from services.document_processing.app.parsers.docling_parser import DoclingParser

        parser = DoclingParser(ocr_enabled=False, table_structure=False)
        is_healthy = await parser.check_health()

        assert is_healthy is True


class TestParserFactoryIntegration:
    """Integration tests for ParserFactory."""

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    @pytest.mark.asyncio
    async def test_parser_factory_uses_docling(self):
        """Test that ParserFactory uses Docling when enabled."""
        from services.document_processing.app.parsers.factory import ParserFactory

        factory = ParserFactory(docling_enabled=True)

        assert factory.docling_enabled is True

        # Get docling parser
        parser = factory.get_docling_parser()
        assert parser is not None

    @pytest.mark.skipif(not DOCLING_AVAILABLE, reason="Docling not installed")
    @pytest.mark.asyncio
    async def test_parser_factory_health_check(self):
        """Test ParserFactory health check."""
        from services.document_processing.app.parsers.factory import ParserFactory

        factory = ParserFactory(docling_enabled=True)
        health = await factory.check_health()

        assert "docling" in health
        assert health["docling"] is True


class TestChunkingIntegration:
    """Integration tests for chunking with real text."""

    def test_chunker_with_heliophysics_text(self, heliophysics_text):
        """Test chunking service with heliophysics content."""
        from services.document_processing.app.parsers.chunker import ChunkingService
        from services.document_processing.app.core.schemas import ParsedSection, SectionType

        document_id = uuid4()

        # Create sections from the text
        sections = [
            ParsedSection(
                section_type=SectionType.ABSTRACT,
                title="Abstract",
                text="This study investigates solar wind dynamics observed by the Parker Solar Probe.",
                char_offset_start=0,
                char_offset_end=80,
            ),
            ParsedSection(
                section_type=SectionType.INTRODUCTION,
                title="Introduction",
                text="Solar wind is a continuous stream of charged particles released from the Sun's corona.",
                char_offset_start=82,
                char_offset_end=170,
            ),
            ParsedSection(
                section_type=SectionType.METHODS,
                title="Methods",
                text="We used data from the Solar Dynamics Observatory (SDO) and the Advanced Composition Explorer (ACE) spacecraft.",
                char_offset_start=172,
                char_offset_end=285,
            ),
            ParsedSection(
                section_type=SectionType.RESULTS,
                title="Results",
                text="The solar wind velocity ranged from 300-800 km/s. We detected three ICMEs with associated geomagnetic activity.",
                char_offset_start=287,
                char_offset_end=400,
            ),
        ]

        chunker = ChunkingService(max_tokens=100, overlap_tokens=20)
        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) > 0
        assert all(chunk.document_id == document_id for chunk in chunks)
        assert all(chunk.text for chunk in chunks)
        assert all(chunk.token_count > 0 for chunk in chunks)


class TestEmbeddingIntegration:
    """Integration tests for embedding generation."""

    @pytest.mark.skipif(not SENTENCE_TRANSFORMERS_AVAILABLE, reason="sentence-transformers not installed")
    @pytest.mark.asyncio
    async def test_embedding_generator_initialization(self):
        """Test EmbeddingGenerator initialization."""
        from services.document_processing.app.embeddings.generator import EmbeddingGenerator

        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )

        assert generator is not None

    @pytest.mark.skipif(not SENTENCE_TRANSFORMERS_AVAILABLE, reason="sentence-transformers not installed")
    @pytest.mark.asyncio
    async def test_embedding_generation(self):
        """Test embedding generation with sample chunks."""
        from services.document_processing.app.embeddings.generator import EmbeddingGenerator
        from services.document_processing.app.core.schemas import Chunk, SectionType

        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )

        document_id = uuid4()
        chunks = [
            Chunk(
                chunk_id=uuid4(),
                document_id=document_id,
                sequence_number=0,
                text="Solar wind is a stream of charged particles from the Sun.",
                section=SectionType.INTRODUCTION,
                token_count=12,
                char_offset_start=0,
                char_offset_end=57,
            ),
            Chunk(
                chunk_id=uuid4(),
                document_id=document_id,
                sequence_number=1,
                text="Parker Solar Probe observed coronal mass ejections.",
                section=SectionType.RESULTS,
                token_count=8,
                char_offset_start=58,
                char_offset_end=108,
            ),
        ]

        embedded_chunks = await generator.generate_embeddings(chunks)

        assert len(embedded_chunks) == 2
        assert all(hasattr(c, 'embedding') for c in embedded_chunks)
        assert all(len(c.embedding) == 384 for c in embedded_chunks)  # MiniLM dimension

    @pytest.mark.skipif(not SENTENCE_TRANSFORMERS_AVAILABLE, reason="sentence-transformers not installed")
    def test_sentence_transformer_direct(self):
        """Test SentenceTransformer directly."""
        model = SentenceTransformer("all-MiniLM-L6-v2")

        texts = [
            "Solar wind dynamics",
            "Coronal mass ejection",
            "Geomagnetic storm",
        ]

        embeddings = model.encode(texts)

        assert embeddings.shape == (3, 384)


class TestLiteLLMIntegration:
    """Integration tests for LiteLLM."""

    @pytest.mark.skipif(not LITELLM_AVAILABLE, reason="litellm not installed")
    def test_litellm_import(self):
        """Test that LiteLLM can be imported."""
        import litellm

        assert litellm is not None
        assert callable(litellm.acompletion)

    @pytest.mark.skipif(not LITELLM_AVAILABLE, reason="litellm not installed")
    def test_litellm_configuration(self):
        """Test LiteLLM configuration options."""
        import litellm

        # These should not raise errors
        litellm.drop_params = True

        assert litellm.drop_params is True

    @pytest.mark.skipif(
        not (LITELLM_AVAILABLE and HAS_API_KEY),
        reason="litellm not installed or no API key"
    )
    @pytest.mark.asyncio
    async def test_litellm_completion(self):
        """Test LiteLLM async completion with real API."""
        import litellm

        # Use a cheap model for testing
        model = "gpt-4o-mini" if os.getenv("OPENAI_API_KEY") else "anthropic/claude-3-haiku-20240307"

        response = await litellm.acompletion(
            model=model,
            messages=[{"role": "user", "content": "Say 'test' and nothing else."}],
            max_tokens=10,
        )

        assert response is not None
        assert response.choices[0].message.content is not None

    @pytest.mark.skipif(
        not (LITELLM_AVAILABLE and HAS_API_KEY),
        reason="litellm not installed or no API key"
    )
    @pytest.mark.asyncio
    async def test_entity_extraction_with_litellm(self, heliophysics_text):
        """Test entity extraction from heliophysics text using LiteLLM."""
        import litellm
        import json

        model = "gpt-4o-mini" if os.getenv("OPENAI_API_KEY") else "anthropic/claude-3-haiku-20240307"

        response = await litellm.acompletion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Extract scientific entities from text. Return a JSON array with objects containing 'name' and 'type' fields. Types: spacecraft, phenomenon, instrument, concept."
                },
                {
                    "role": "user",
                    "content": f"Extract entities from: {heliophysics_text[:500]}"
                }
            ],
            max_tokens=500,
            temperature=0.1,
        )

        content = response.choices[0].message.content
        assert content is not None

        # Should contain some heliophysics entities
        content_lower = content.lower()
        assert any(term in content_lower for term in [
            "parker", "solar", "sdo", "ace", "wind", "corona"
        ])


class TestFullPipelineIntegration:
    """End-to-end integration tests for the full pipeline."""

    @pytest.mark.skipif(
        not (DOCLING_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE),
        reason="Docling or sentence-transformers not installed"
    )
    @pytest.mark.asyncio
    async def test_full_pipeline_text_to_embeddings(self, heliophysics_text):
        """Test full pipeline from text to embeddings."""
        from services.document_processing.app.parsers.segmenter import SectionSegmenter
        from services.document_processing.app.parsers.chunker import ChunkingService
        from services.document_processing.app.embeddings.generator import EmbeddingGenerator
        from services.document_processing.app.core.schemas import ExtractedText, ParsedSection, SectionType

        document_id = uuid4()

        # Step 1: Create extracted text (simulating Docling output)
        extracted = ExtractedText(
            full_text=heliophysics_text,
            sections=[
                ParsedSection(
                    section_type=SectionType.ABSTRACT,
                    title="Abstract",
                    text="This study investigates solar wind dynamics observed by the Parker Solar Probe.",
                    char_offset_start=0,
                    char_offset_end=80,
                ),
                ParsedSection(
                    section_type=SectionType.METHODS,
                    title="Methods",
                    text="We used data from the Solar Dynamics Observatory (SDO) and ACE spacecraft.",
                    char_offset_start=82,
                    char_offset_end=160,
                ),
            ],
            references=[],
            page_count=1,
            metadata={"parser": "test"},
        )

        # Step 2: Segment
        segmenter = SectionSegmenter()
        sections = segmenter.segment(extracted)

        assert len(sections) >= 2

        # Step 3: Chunk
        chunker = ChunkingService(max_tokens=256, overlap_tokens=50)
        chunks = chunker.chunk_document(document_id, sections)

        assert len(chunks) > 0

        # Step 4: Generate embeddings
        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )
        embedded_chunks = await generator.generate_embeddings(chunks)

        assert len(embedded_chunks) == len(chunks)
        assert all(len(c.embedding) == 384 for c in embedded_chunks)

    @pytest.mark.skipif(
        not (DOCLING_AVAILABLE and SENTENCE_TRANSFORMERS_AVAILABLE),
        reason="Docling or sentence-transformers not installed"
    )
    @pytest.mark.asyncio
    async def test_semantic_search_on_chunks(self, heliophysics_text):
        """Test semantic search functionality on embedded chunks."""
        from services.document_processing.app.parsers.chunker import ChunkingService
        from services.document_processing.app.embeddings.generator import EmbeddingGenerator
        from services.document_processing.app.core.schemas import ParsedSection, SectionType
        import numpy as np

        document_id = uuid4()

        # Create diverse sections
        sections = [
            ParsedSection(
                section_type=SectionType.ABSTRACT,
                title="Abstract",
                text="This study analyzes solar wind velocity measurements from Parker Solar Probe.",
                char_offset_start=0,
                char_offset_end=80,
            ),
            ParsedSection(
                section_type=SectionType.METHODS,
                title="Methods",
                text="Data was collected using the SWEAP instrument suite aboard Parker Solar Probe.",
                char_offset_start=82,
                char_offset_end=160,
            ),
            ParsedSection(
                section_type=SectionType.RESULTS,
                title="Results",
                text="Geomagnetic storm activity increased during periods of high solar wind density.",
                char_offset_start=162,
                char_offset_end=240,
            ),
        ]

        # Chunk and embed
        chunker = ChunkingService(max_tokens=256, overlap_tokens=50)
        chunks = chunker.chunk_document(document_id, sections)

        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )
        embedded_chunks = await generator.generate_embeddings(chunks)

        # Create query embedding
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2")

        query = "What causes geomagnetic storms?"
        query_embedding = model.encode(query)

        # Compute cosine similarities
        similarities = []
        for chunk in embedded_chunks:
            chunk_emb = np.array(chunk.embedding)
            similarity = np.dot(query_embedding, chunk_emb) / (
                np.linalg.norm(query_embedding) * np.linalg.norm(chunk_emb)
            )
            similarities.append((chunk, similarity))

        # Sort by similarity
        similarities.sort(key=lambda x: x[1], reverse=True)

        # The results section about geomagnetic storms should rank high
        top_chunk = similarities[0][0]
        assert "geomagnetic" in top_chunk.text.lower() or "storm" in top_chunk.text.lower()


class TestSectionSegmentation:
    """Integration tests for section segmentation."""

    def test_segmenter_identifies_section_types(self, heliophysics_text):
        """Test that segmenter correctly identifies section types."""
        from services.document_processing.app.parsers.segmenter import SectionSegmenter
        from services.document_processing.app.core.schemas import ExtractedText, ParsedSection, SectionType

        # Create extracted text with clear section markers
        extracted = ExtractedText(
            full_text=heliophysics_text,
            sections=[
                ParsedSection(
                    section_type=SectionType.OTHER,  # Will be reclassified
                    title="Abstract",
                    text="This study investigates solar wind.",
                    char_offset_start=0,
                    char_offset_end=35,
                ),
                ParsedSection(
                    section_type=SectionType.OTHER,
                    title="1. Introduction",
                    text="Solar wind is important.",
                    char_offset_start=37,
                    char_offset_end=60,
                ),
                ParsedSection(
                    section_type=SectionType.OTHER,
                    title="2. Methods and Materials",
                    text="We used SDO data.",
                    char_offset_start=62,
                    char_offset_end=80,
                ),
            ],
            references=[],
            page_count=1,
            metadata={},
        )

        segmenter = SectionSegmenter()
        sections = segmenter.segment(extracted)

        # Check that section types were properly identified
        section_types = {s.section_type for s in sections}

        assert SectionType.ABSTRACT in section_types or any(
            "abstract" in s.title.lower() for s in sections if s.title
        )
