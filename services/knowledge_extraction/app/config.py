"""Configuration for the Knowledge Extraction service."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Knowledge Extraction service settings."""

    # Service settings
    SERVICE_NAME: str = "knowledge-extraction"
    DEBUG: bool = False
    LOG_JSON: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"

    # Neo4j
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "heliograph123"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage settings
    STORAGE_TYPE: str = "s3"  # 's3' or 'local'
    LOCAL_STORAGE_PATH: str = "/data/heliograph"  # Used when STORAGE_TYPE='local'

    # S3 settings (used when STORAGE_TYPE='s3')
    S3_BUCKET: str = "heliograph-documents"
    S3_ENDPOINT_URL: str | None = None

    # SQS
    SQS_DOCUMENT_INDEXED_URL: str = "http://localhost:4566/000000000000/document-indexed"
    SQS_KNOWLEDGE_EXTRACTED_URL: str = "http://localhost:4566/000000000000/knowledge-extracted"
    SQS_ENDPOINT_URL: str | None = None

    # Document Registry
    DOCUMENT_REGISTRY_URL: str = "http://localhost:8000"

    # Extraction settings
    EXTRACTION_PROVIDER: Literal["openai", "anthropic", "local"] = "openai"
    OPENAI_API_KEY: str | None = None
    ANTHROPIC_API_KEY: str | None = None
    EXTRACTION_MODEL: str = "gpt-4o-mini"  # or claude-3-haiku, local model name
    LOCAL_MODEL_NAME: str = "llama2"  # Local model for Ollama

    # LiteLLM unified client (recommended)
    # Uses single API for all providers with automatic fallbacks
    USE_LITELLM: bool = True

    # LangChain extractor settings (alternative to custom extraction)
    # Set USE_LANGCHAIN_EXTRACTOR=true to use LangChain's LLMGraphTransformer
    # which provides single-pass extraction with constrained entity/relationship types
    # Inspired by: https://github.com/calexyoung/knowledge-graph-llms
    USE_LANGCHAIN_EXTRACTOR: bool = False
    CONSTRAINED_EXTRACTION: bool = True  # Use heliophysics-specific constraints
    USE_HYBRID_EXTRACTOR: bool = False  # Combine LangChain with custom normalization

    # Entity extraction
    MIN_ENTITY_CONFIDENCE: float = 0.7
    MAX_ENTITIES_PER_CHUNK: int = 20
    ENTITY_TYPES: list[str] = [
        "scientific_concept",
        "method",
        "dataset",
        "instrument",
        "phenomenon",
        "mission",
        "spacecraft",
        "celestial_body",
        "organization",
    ]

    # Relationship extraction
    MIN_RELATIONSHIP_CONFIDENCE: float = 0.6
    MAX_RELATIONSHIPS_PER_CHUNK: int = 30
    RELATIONSHIP_TYPES: list[str] = [
        "cites",
        "authored_by",
        "uses_method",
        "uses_dataset",
        "uses_instrument",
        "studies",
        "mentions",
        "related_to",
        "part_of",
        "causes",
        "observes",
    ]

    # Batch processing
    BATCH_SIZE: int = 10
    MAX_CONCURRENT_EXTRACTIONS: int = 5

    model_config = {"env_prefix": "EXTRACTION_"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
