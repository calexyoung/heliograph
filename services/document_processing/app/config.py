"""Document Processing Service configuration."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Service settings."""

    model_config = SettingsConfigDict(
        env_prefix="PROCESSING_",
        case_sensitive=True,
        extra="ignore",
    )

    # Service
    SERVICE_NAME: str = "document-processing"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Storage settings
    STORAGE_TYPE: str = "s3"  # 's3' or 'local'
    LOCAL_STORAGE_PATH: str = "/data/heliograph"  # Used when STORAGE_TYPE='local'

    # AWS / S3 (used when STORAGE_TYPE='s3')
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_BUCKET: str = "heliograph-documents"
    S3_ENDPOINT_URL: str | None = None  # For LocalStack

    # SQS
    SQS_ENDPOINT_URL: str | None = None
    SQS_DOCUMENT_REGISTERED_URL: str = ""
    SQS_DOCUMENT_INDEXED_URL: str = ""
    SQS_DLQ_URL: str = ""

    # Document Registry Service
    DOCUMENT_REGISTRY_URL: str = "http://localhost:8000"

    # Knowledge Extraction Service
    KNOWLEDGE_EXTRACTION_URL: str = "http://localhost:8004"
    ENABLE_KNOWLEDGE_EXTRACTION: bool = True

    # GROBID (legacy, used as fallback for scientific PDFs)
    GROBID_URL: str = "http://localhost:8070"
    GROBID_TIMEOUT: int = 300  # 5 minutes

    # Docling (primary parser - supports PDF, DOCX, PPTX, XLSX, HTML, images)
    DOCLING_ENABLED: bool = True  # Use Docling as primary parser
    DOCLING_OCR_ENABLED: bool = True  # Enable OCR for scanned documents
    DOCLING_TABLE_STRUCTURE: bool = True  # Extract table structure
    DOCLING_TIMEOUT: int = 300  # 5 minutes

    # Embedding Model
    EMBEDDING_PROVIDER: str = "sentence_transformers"  # openai, sentence_transformers
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    EMBEDDING_DIMENSION: int = 384
    EMBEDDING_BATCH_SIZE: int = 32

    # OpenAI (if using)
    OPENAI_API_KEY: str = ""
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "heliograph_chunks"

    # Hybrid Search (combines dense vectors + sparse BM25)
    ENABLE_HYBRID_SEARCH: bool = True  # Enable hybrid dense+sparse indexing

    # Chunking
    CHUNK_MAX_TOKENS: int = 512
    CHUNK_OVERLAP_TOKENS: int = 100  # Increased for better context preservation
    CHUNK_RESPECT_SECTIONS: bool = True

    # Pipeline
    PIPELINE_MAX_RETRIES: int = 3
    PIPELINE_RETRY_DELAY: int = 60  # seconds
    PIPELINE_VISIBILITY_TIMEOUT: int = 600  # 10 minutes

    # Metrics
    METRICS_ENABLED: bool = True

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings."""
    return Settings()


settings = get_settings()
