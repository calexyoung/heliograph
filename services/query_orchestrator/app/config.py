"""Configuration for the Query Orchestrator service."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Query Orchestrator service settings."""

    # Service settings
    SERVICE_NAME: str = "query-orchestrator"
    DEBUG: bool = False
    LOG_JSON: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "heliograph_chunks"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "heliograph123"

    # LLM Generation Service
    LLM_SERVICE_URL: str = "http://localhost:8005"

    # Embedding settings
    EMBEDDING_PROVIDER: Literal["sentence_transformers", "openai"] = "sentence_transformers"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    OPENAI_API_KEY: str | None = None

    # Retrieval settings
    VECTOR_TOP_K: int = 30  # Increased for better recall
    GRAPH_EXPANSION_DEPTH: int = 2  # Expanded for richer context
    GRAPH_MAX_NODES: int = 75  # Allow more graph context
    MIN_SIMILARITY_SCORE: float = 0.2  # Filter very weak matches

    # Hybrid search settings (combines dense vectors + sparse BM25)
    ENABLE_HYBRID_SEARCH: bool = True  # Enable hybrid dense+sparse retrieval
    HYBRID_DENSE_WEIGHT: float = 0.7  # Weight for dense vector results
    HYBRID_SPARSE_WEIGHT: float = 0.3  # Weight for sparse BM25 results

    # Evidence summarization (paper-qa inspired)
    ENABLE_EVIDENCE_SUMMARIZATION: bool = True  # Summarize chunks before answer generation
    EVIDENCE_SUMMARIZATION_MAX_CONCURRENT: int = 5  # Max concurrent summarization requests

    # Re-ranking settings
    RERANK_ENABLED: bool = True
    RERANK_TOP_K: int = 12  # Slightly more candidates for diversity
    RERANK_MODEL: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # Context settings
    MAX_CONTEXT_TOKENS: int = 6000  # More context for better answers
    MAX_CHUNKS_IN_CONTEXT: int = 18  # Allow more chunks
    INCLUDE_METADATA: bool = True

    # Query understanding
    QUERY_EXPANSION_ENABLED: bool = True
    ENTITY_EXTRACTION_ENABLED: bool = True

    model_config = {"env_prefix": "QUERY_"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
