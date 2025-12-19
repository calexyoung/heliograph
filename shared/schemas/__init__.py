"""Shared Pydantic schemas for HelioGraph services."""

from shared.schemas.author import AuthorSchema
from shared.schemas.document import (
    DocumentMetadata,
    DocumentStatus,
    ProvenanceEntry,
)
from shared.schemas.events import (
    DocumentDuplicateEvent,
    DocumentRegisteredEvent,
    StateTransitionFailedEvent,
)
from shared.schemas.api_responses import (
    APIResponse,
    ErrorResponse,
    PaginatedResponse,
)

__all__ = [
    "AuthorSchema",
    "DocumentMetadata",
    "DocumentStatus",
    "ProvenanceEntry",
    "DocumentRegisteredEvent",
    "DocumentDuplicateEvent",
    "StateTransitionFailedEvent",
    "APIResponse",
    "ErrorResponse",
    "PaginatedResponse",
]
