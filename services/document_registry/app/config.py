"""Service configuration via environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Document Registry Service configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="REGISTRY_",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars not in this model
    )

    # Service settings
    service_name: str = "document-registry"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Database settings
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # SQS settings
    sqs_queue_url: str = "http://localhost:4566/000000000000/document-registered"
    sqs_region: str = "us-east-1"
    sqs_endpoint_url: str | None = "http://localhost:4566"  # LocalStack

    # Storage settings
    storage_type: str = "s3"  # 's3' or 'local'
    local_storage_path: str = "/data/heliograph"  # Used when storage_type='local'

    # S3 settings (used when storage_type='s3')
    s3_bucket: str = "heliograph-documents"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = "http://localhost:4566"  # LocalStack

    # Deduplication settings
    fuzzy_match_threshold: float = 0.9  # Levenshtein ratio for fuzzy title matching

    # API settings
    api_prefix: str = "/registry"
    cors_origins: list[str] = ["http://localhost:3000"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # Rate limiting settings
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
