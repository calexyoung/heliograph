"""API dependencies."""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from services.document_processing.app.config import settings
from services.document_processing.app.embeddings.generator import EmbeddingGenerator
from services.document_processing.app.embeddings.qdrant import QdrantClient
from services.document_processing.app.parsers.grobid import GrobidParser
from services.document_processing.app.pipeline.orchestrator import PipelineOrchestrator
from shared.utils.db import get_session

# Singleton instances
_qdrant_client: QdrantClient | None = None
_embedding_generator: EmbeddingGenerator | None = None
_grobid_parser: GrobidParser | None = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Get database session."""
    async with get_session() as session:
        yield session


def get_qdrant_client() -> QdrantClient:
    """Get Qdrant client singleton."""
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            collection_name=settings.QDRANT_COLLECTION,
        )
    return _qdrant_client


def get_embedding_generator() -> EmbeddingGenerator:
    """Get embedding generator singleton."""
    global _embedding_generator
    if _embedding_generator is None:
        _embedding_generator = EmbeddingGenerator(
            provider=settings.EMBEDDING_PROVIDER,
            model_name=settings.EMBEDDING_MODEL,
            openai_api_key=settings.OPENAI_API_KEY,
            batch_size=settings.EMBEDDING_BATCH_SIZE,
        )
    return _embedding_generator


def get_grobid_parser() -> GrobidParser:
    """Get GROBID parser singleton."""
    global _grobid_parser
    if _grobid_parser is None:
        _grobid_parser = GrobidParser(
            grobid_url=settings.GROBID_URL,
            timeout=settings.GROBID_TIMEOUT,
        )
    return _grobid_parser


async def get_orchestrator() -> AsyncGenerator[PipelineOrchestrator, None]:
    """Get pipeline orchestrator with dependencies."""
    async with get_session() as session:
        orchestrator = PipelineOrchestrator(db=session)
        yield orchestrator


async def cleanup_dependencies() -> None:
    """Cleanup singleton instances on shutdown."""
    global _qdrant_client, _embedding_generator, _grobid_parser

    if _qdrant_client:
        await _qdrant_client.close()
        _qdrant_client = None

    _embedding_generator = None
    _grobid_parser = None
