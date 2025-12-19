"""Ingestion Service configuration via environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Ingestion Service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="INGESTION_",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars not defined in this model
    )

    # Service settings
    service_name: str = "ingestion"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Database settings
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Redis settings
    redis_url: str = "redis://localhost:6379/0"

    # Storage settings
    storage_type: str = "s3"  # 's3' or 'local'
    local_storage_path: str = "/data/heliograph"  # Used when storage_type='local'

    # S3 settings (used when storage_type='s3')
    s3_bucket: str = "heliograph-documents"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = "http://localhost:4566"

    # Document Registry service
    document_registry_url: str = "http://localhost:8000"

    # SQS settings
    sqs_document_events_url: str = ""  # SQS queue URL for document events

    # Crossref API settings
    crossref_api_url: str = "https://api.crossref.org"
    crossref_mailto: str = ""  # Polite pool requires email
    crossref_rate_limit: float = 50.0  # Requests per second with polite pool

    # Semantic Scholar API settings
    semantic_scholar_api_url: str = "https://api.semanticscholar.org/graph/v1"
    semantic_scholar_api_key: str = ""
    semantic_scholar_rate_limit: float = 100.0  # Requests per 5 minutes

    # arXiv API settings
    arxiv_api_url: str = "http://export.arxiv.org/api/query"
    arxiv_rate_limit: float = 0.33  # 3 seconds between requests

    # NASA ADS / SciXplorer settings
    ads_api_url: str = "https://api.adsabs.harvard.edu/v1"
    ads_api_token: str = ""
    ads_rate_limit: float = 5.0  # Requests per second (5000/day)

    # Job settings
    job_timeout_seconds: int = 3600  # 1 hour
    max_concurrent_downloads: int = 5
    download_chunk_size: int = 8192

    # Upload settings
    max_upload_size_mb: int = 50
    allowed_content_types: list[str] = ["application/pdf"]

    # CORS settings
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Module-level settings instance for direct import
settings = get_settings()
