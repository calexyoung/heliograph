"""API Gateway configuration via environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API Gateway configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="GATEWAY_",
        case_sensitive=False,
        extra="ignore",  # Ignore extra env vars not defined in this model
    )

    # Service settings
    service_name: str = "api-gateway"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_json: bool = True

    # Database settings (for user management)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/heliograph"
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # Redis settings (for sessions and rate limiting)
    redis_url: str = "redis://localhost:6379/0"
    session_ttl_seconds: int = 86400  # 24 hours

    # JWT settings
    jwt_secret_key: str = Field(default="change-me-in-production", description="JWT signing key")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440  # 24 hours
    jwt_refresh_token_expire_days: int = 30

    # OAuth/OIDC settings (for external providers)
    oauth_enabled: bool = False
    oauth_provider: str = "auth0"  # auth0, cognito, or custom
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    oauth_issuer_url: str = ""
    oauth_audience: str = ""

    # API key settings
    api_key_header: str = "X-API-Key"
    service_api_keys: dict[str, str] = Field(
        default_factory=dict,
        description="Map of service names to API keys",
    )

    # Rate limiting settings
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60
    rate_limit_burst: int = 10

    # Storage settings (for file uploads)
    storage_type: str = "s3"  # 's3' or 'local'
    storage_bucket: str = "heliograph-documents"
    local_storage_path: str = "/data/heliograph"  # Used when storage_type='local'

    # S3-specific settings (used when storage_type='s3')
    s3_bucket: str = "heliograph-documents"
    s3_region: str = "us-east-1"
    s3_endpoint_url: str | None = "http://localhost:4566"
    s3_public_endpoint_url: str | None = "http://localhost:4566"  # URL for browser access
    max_upload_size_mb: int = 50
    presigned_url_expiry_seconds: int = 3600

    # Backend service URLs
    document_registry_url: str = "http://localhost:8000"
    ingestion_service_url: str = "http://localhost:8002"
    query_orchestrator_url: str = "http://localhost:8006"
    knowledge_extraction_url: str = "http://localhost:8004"

    # Circuit breaker settings
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_recovery_timeout: int = 30
    circuit_breaker_half_open_requests: int = 3

    # CORS settings
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]

    # WebSocket/SSE settings
    ws_heartbeat_interval: int = 30
    sse_retry_timeout: int = 3000


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
