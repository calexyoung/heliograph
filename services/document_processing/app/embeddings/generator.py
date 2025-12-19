"""Embedding generation for document chunks."""

import asyncio
from typing import Any

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import Chunk, ChunkWithEmbedding
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class EmbeddingGenerator:
    """Generate embeddings for text chunks."""

    def __init__(
        self,
        provider: str = "sentence_transformers",
        model_name: str = "all-MiniLM-L6-v2",
        openai_api_key: str = "",
        batch_size: int = 32,
    ):
        """Initialize embedding generator.

        Args:
            provider: Embedding provider (sentence_transformers, openai)
            model_name: Model name
            openai_api_key: OpenAI API key (if using OpenAI)
            batch_size: Batch size for embedding generation
        """
        self.provider = provider
        self.model_name = model_name
        self.openai_api_key = openai_api_key
        self.batch_size = batch_size

        self._model = None
        self._openai_client = None

    async def generate_embeddings(
        self,
        chunks: list[Chunk],
    ) -> list[ChunkWithEmbedding]:
        """Generate embeddings for chunks.

        Args:
            chunks: List of chunks

        Returns:
            Chunks with embeddings
        """
        if not chunks:
            return []

        # Extract texts
        texts = [chunk.text for chunk in chunks]

        # Generate embeddings in batches
        all_embeddings = []

        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]

            if self.provider == "openai":
                embeddings = await self._generate_openai(batch)
            else:
                embeddings = await self._generate_sentence_transformers(batch)

            all_embeddings.extend(embeddings)

        logger.info(
            "embeddings_generated",
            count=len(chunks),
            provider=self.provider,
            model=self.model_name,
        )

        # Create ChunkWithEmbedding objects
        return [
            ChunkWithEmbedding(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                sequence_number=chunk.sequence_number,
                text=chunk.text,
                section=chunk.section,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_offset_start=chunk.char_offset_start,
                char_offset_end=chunk.char_offset_end,
                token_count=chunk.token_count,
                metadata=chunk.metadata,
                embedding=embedding,
            )
            for chunk, embedding in zip(chunks, all_embeddings)
        ]

    async def _generate_sentence_transformers(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings using sentence-transformers.

        Args:
            texts: List of texts

        Returns:
            List of embedding vectors
        """
        if self._model is None:
            self._model = await self._load_sentence_transformers_model()

        # Run in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(
            None,
            lambda: self._model.encode(texts, convert_to_tensor=False).tolist(),
        )

        return embeddings

    async def _load_sentence_transformers_model(self) -> Any:
        """Load sentence-transformers model.

        Returns:
            SentenceTransformer model
        """
        try:
            from sentence_transformers import SentenceTransformer

            logger.info("loading_sentence_transformer", model=self.model_name)

            loop = asyncio.get_event_loop()
            model = await loop.run_in_executor(
                None,
                lambda: SentenceTransformer(self.model_name),
            )

            logger.info("sentence_transformer_loaded", model=self.model_name)
            return model

        except ImportError:
            raise RuntimeError(
                "sentence-transformers not installed. "
                "Install with: pip install sentence-transformers"
            )

    async def _generate_openai(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        """Generate embeddings using OpenAI API.

        Args:
            texts: List of texts

        Returns:
            List of embedding vectors
        """
        if self._openai_client is None:
            self._openai_client = await self._create_openai_client()

        response = await self._openai_client.embeddings.create(
            model=self.model_name or settings.OPENAI_EMBEDDING_MODEL,
            input=texts,
        )

        return [item.embedding for item in response.data]

    async def _create_openai_client(self) -> Any:
        """Create OpenAI client.

        Returns:
            OpenAI async client
        """
        try:
            from openai import AsyncOpenAI

            api_key = self.openai_api_key or settings.OPENAI_API_KEY
            if not api_key:
                raise ValueError("OpenAI API key not provided")

            return AsyncOpenAI(api_key=api_key)

        except ImportError:
            raise RuntimeError(
                "openai not installed. Install with: pip install openai"
            )

    async def generate_single(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        if self.provider == "openai":
            embeddings = await self._generate_openai([text])
        else:
            embeddings = await self._generate_sentence_transformers([text])

        return embeddings[0]

    def get_dimension(self) -> int:
        """Get embedding dimension.

        Returns:
            Embedding dimension
        """
        # Known dimensions for common models
        dimensions = {
            "all-MiniLM-L6-v2": 384,
            "all-mpnet-base-v2": 768,
            "paraphrase-MiniLM-L6-v2": 384,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "text-embedding-ada-002": 1536,
        }

        return dimensions.get(self.model_name, settings.EMBEDDING_DIMENSION)
