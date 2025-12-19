"""Configuration for the LLM Generation service."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """LLM Generation service settings."""

    # Service settings
    SERVICE_NAME: str = "llm-generation"
    DEBUG: bool = False
    LOG_JSON: bool = True

    # Redis (for caching)
    REDIS_URL: str = "redis://localhost:6379/0"

    # LLM Provider settings
    DEFAULT_PROVIDER: Literal["openai", "anthropic", "local"] = "openai"

    # LiteLLM unified client (recommended for production)
    # When enabled, uses LiteLLM for all providers with automatic fallbacks
    USE_LITELLM: bool = True  # Set to False to use legacy per-provider clients

    # OpenAI settings
    OPENAI_API_KEY: str | None = None
    OPENAI_MODEL: str = "gpt-4o"
    OPENAI_MAX_TOKENS: int = 2000
    OPENAI_TEMPERATURE: float = 0.3

    # Anthropic settings
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-3-5-sonnet-20241022"
    ANTHROPIC_MAX_TOKENS: int = 2000
    ANTHROPIC_TEMPERATURE: float = 0.3

    # Local model settings (vLLM/Ollama)
    LOCAL_MODEL_URL: str = "http://localhost:8080"
    LOCAL_MODEL_NAME: str = "llama2"
    LOCAL_MAX_TOKENS: int = 2000

    # Generation settings
    CITATION_MODE: Literal["strict", "relaxed"] = "strict"
    MAX_CONTEXT_TOKENS: int = 4000
    RESPONSE_MAX_TOKENS: int = 2000
    STREAM_CHUNK_SIZE: int = 20

    # Safety settings
    ENABLE_CONTENT_FILTER: bool = True
    MAX_PROMPT_LENGTH: int = 20000

    model_config = {"env_prefix": "LLM_"}


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
