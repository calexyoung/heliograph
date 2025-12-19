"""Tests for embedding generation."""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.document_processing.app.core.schemas import Chunk, SectionType
from services.document_processing.app.embeddings.generator import EmbeddingGenerator


class TestEmbeddingGenerator:
    """Tests for embedding generator."""

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks."""
        return [
            Chunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                sequence_number=0,
                text="This is the first chunk about solar flares.",
                section=SectionType.ABSTRACT,
                char_offset_start=0,
                char_offset_end=43,
                token_count=8,
            ),
            Chunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                sequence_number=1,
                text="This is the second chunk about heliophysics.",
                section=SectionType.INTRODUCTION,
                char_offset_start=45,
                char_offset_end=89,
                token_count=7,
            ),
        ]

    def test_get_dimension_known_model(self):
        """Test getting dimension for known models."""
        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )

        assert generator.get_dimension() == 384

    def test_get_dimension_openai(self):
        """Test getting dimension for OpenAI models."""
        generator = EmbeddingGenerator(
            provider="openai",
            model_name="text-embedding-3-small",
        )

        assert generator.get_dimension() == 1536

    @pytest.mark.asyncio
    async def test_generate_single_sentence_transformers(self):
        """Test single embedding generation with sentence transformers."""
        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )

        # Mock the model
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(
            tolist=lambda: [[0.1] * 384]
        )
        generator._model = mock_model

        embedding = await generator.generate_single("Test text")

        assert len(embedding) == 384
        mock_model.encode.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch(self, sample_chunks):
        """Test batch embedding generation."""
        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
            batch_size=10,
        )

        # Mock the model
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(
            tolist=lambda: [[0.1] * 384 for _ in range(len(sample_chunks))]
        )
        generator._model = mock_model

        chunks_with_embeddings = await generator.generate_embeddings(sample_chunks)

        assert len(chunks_with_embeddings) == len(sample_chunks)
        for chunk in chunks_with_embeddings:
            assert hasattr(chunk, "embedding")
            assert len(chunk.embedding) == 384

    @pytest.mark.asyncio
    async def test_generate_embeddings_empty(self):
        """Test embedding generation with empty list."""
        generator = EmbeddingGenerator(
            provider="sentence_transformers",
            model_name="all-MiniLM-L6-v2",
        )

        result = await generator.generate_embeddings([])

        assert result == []

    @pytest.mark.asyncio
    async def test_generate_openai_embeddings(self, sample_chunks):
        """Test OpenAI embedding generation."""
        generator = EmbeddingGenerator(
            provider="openai",
            model_name="text-embedding-3-small",
            openai_api_key="test-key",
        )

        # Mock OpenAI client
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * 1536) for _ in sample_chunks
        ]
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)
        generator._openai_client = mock_client

        chunks_with_embeddings = await generator.generate_embeddings(sample_chunks)

        assert len(chunks_with_embeddings) == len(sample_chunks)
        mock_client.embeddings.create.assert_called_once()
