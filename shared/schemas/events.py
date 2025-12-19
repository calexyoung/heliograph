"""Event schemas for SQS messaging."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base event schema."""

    correlation_id: str = Field(..., description="Request correlation ID for tracing")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class DocumentRegisteredEvent(BaseEvent):
    """Event published when a new document is registered and ready for processing."""

    event_type: Literal["DocumentRegistered"] = "DocumentRegistered"
    document_id: UUID
    content_hash: Optional[str] = None
    doi: Optional[str] = None
    title: str
    s3_key: Optional[str] = None
    user_id: UUID


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
