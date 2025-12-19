"""Pydantic schemas for LLM Generation service."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CitationInfo(BaseModel):
    """Citation information for context."""

    citation_id: int
    chunk_id: UUID
    document_id: UUID
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    page: int | None = None
    section: str | None = None
    snippet: str


class GenerationRequest(BaseModel):
    """Request for LLM generation."""

    query: str
    context: str
    citations: list[CitationInfo]
    intent: str | None = None
    provider: str | None = None  # Override default provider
    model: str | None = None  # Override default model
    temperature: float | None = None
    max_tokens: int | None = None
    citation_mode: str | None = None  # "strict" or "relaxed"


class GenerationResponse(BaseModel):
    """Response from LLM generation."""

    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    citations_used: list[int] = Field(default_factory=list)
    model_used: str
    provider_used: str
    tokens_used: int = 0
    generation_time_ms: float


class StreamChunk(BaseModel):
    """A chunk in streaming response."""

    type: str  # "text", "citation", "error", "done"
    content: str | None = None
    citation_id: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    """A message in a conversation."""

    role: str  # "system", "user", "assistant"
    content: str


class ConversationRequest(BaseModel):
    """Request for multi-turn conversation."""

    messages: list[Message]
    context: str | None = None
    citations: list[CitationInfo] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


class ConversationResponse(BaseModel):
    """Response from conversation."""

    message: Message
    confidence: float = Field(ge=0.0, le=1.0)
    citations_used: list[int] = Field(default_factory=list)
    model_used: str
    tokens_used: int = 0


class ModelInfo(BaseModel):
    """Information about an available model."""

    provider: str
    model_id: str
    display_name: str
    max_context: int
    supports_streaming: bool = True
    supports_functions: bool = False


class ProviderStatus(BaseModel):
    """Status of a provider."""

    provider: str
    available: bool
    models: list[str] = Field(default_factory=list)  # Model names
    model_info: list[ModelInfo] = Field(default_factory=list)  # Detailed info
    error: str | None = None
    backend: str | None = None  # "litellm" or "legacy"
