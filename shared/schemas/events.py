"""Event schemas for SQS messaging."""

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base event schema."""

    correlation_id: str = Field(..., description="Request correlation ID for tracing")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class StorageConfig(BaseModel):
    """Storage configuration for document processing."""

    type: str = Field(default="s3", description="Storage type: 's3' or 'local'")
    local_path: Optional[str] = Field(
        default=None, description="Local filesystem path for local storage"
    )
    bucket: Optional[str] = Field(
        default=None, description="S3 bucket name (optional)"
    )


class DocumentRegisteredEvent(BaseEvent):
    """Event published when a new document is registered and ready for processing."""

    event_type: Literal["DocumentRegistered"] = "DocumentRegistered"
    document_id: UUID
    content_hash: Optional[str] = None
    doi: Optional[str] = None
    title: str
    s3_key: Optional[str] = None
    user_id: UUID

    # Storage configuration for document processing
    storage_config: Optional[StorageConfig] = Field(
        default=None,
        description="Storage configuration (type, local_path, bucket) for processing",
    )


class DocumentDuplicateEvent(BaseEvent):
    """Event published when a duplicate document is detected."""

    event_type: Literal["DocumentDuplicate"] = "DocumentDuplicate"
    new_document_request_hash: str
    existing_document_id: UUID
    match_type: str = Field(
        ..., description="Type of match: doi, content_hash, composite, fuzzy_title"
    )
    user_id: UUID


class DocumentIndexedEvent(BaseEvent):
    """Event published when document processing is complete."""

    event_type: Literal["DocumentIndexed"] = "DocumentIndexed"
    document_id: UUID
    chunk_count: int
    entity_count: int
    processing_time_seconds: float


class StateTransitionFailedEvent(BaseEvent):
    """Event published when a state transition fails."""

    event_type: Literal["StateTransitionFailed"] = "StateTransitionFailed"
    document_id: UUID
    from_state: str
    to_state: str
    error_message: str
    worker_id: str
