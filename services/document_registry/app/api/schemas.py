"""Request and response schemas for Document Registry API."""

import re
from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.schemas.author import AuthorSchema
from shared.schemas.document import DocumentStatus, ProvenanceEntry

# S3 key pattern: alphanumeric, hyphens, underscores, periods, forward slashes
# Must start with alphanumeric and not exceed reasonable length
S3_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_./]{0,1023}$")


class DocumentRegistrationRequest(BaseModel):
    """Request schema for document registration."""

    doi: Optional[str] = Field(None, description="Document DOI")
    content_hash: Optional[str] = Field(
        None,
        description="SHA-256 hash of PDF content (required if no DOI)",
        min_length=64,
        max_length=64,
    )
    title: str = Field(..., description="Document title", min_length=1)
    authors: list[AuthorSchema] = Field(default_factory=list, description="List of authors")
    subtitle: Optional[str] = Field(None, description="Document subtitle")
    journal: Optional[str] = Field(None, description="Journal name")
    year: Optional[int] = Field(None, description="Publication year", ge=1800, le=2100)
    source: Literal["upload", "crossref", "semantic_scholar", "arxiv", "scixplorer"] = Field(
        ..., description="Source of the document"
    )
    upload_id: Optional[UUID] = Field(None, description="Upload ID for direct uploads")
    connector_job_id: Optional[UUID] = Field(None, description="Connector job ID for API imports")
    user_id: UUID = Field(..., description="User ID who initiated registration")
    source_metadata: Optional[dict[str, Any]] = Field(
        None, description="Additional source-specific metadata"
    )

    @field_validator("content_hash")
    @classmethod
    def validate_content_hash(cls, v: str | None) -> str | None:
        """Validate content hash is valid hex."""
        if v is None:
            return v
        try:
            int(v, 16)
        except ValueError:
            raise ValueError("content_hash must be a valid hexadecimal string")
        return v.lower()

    @model_validator(mode="after")
    def validate_identifier(self) -> "DocumentRegistrationRequest":
        """Ensure at least DOI or content_hash is provided."""
        if not self.doi and not self.content_hash:
            raise ValueError("Either doi or content_hash must be provided")
        return self


class DocumentRegistrationResponse(BaseModel):
    """Response schema for document registration."""

    document_id: UUID
    status: Literal["queued", "duplicate", "rejected"]
    existing_document_id: Optional[UUID] = Field(
        None, description="If duplicate, the existing document ID"
    )
    rejection_reason: Optional[str] = Field(None, description="If rejected, the reason")


class DocumentDetailResponse(BaseModel):
    """Response schema for document details."""

    document_id: UUID
    doi: Optional[str] = None
    content_hash: Optional[str] = None
    title: str
    authors: list[AuthorSchema] = Field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    status: DocumentStatus
    error_message: Optional[str] = None
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    last_processed_at: Optional[datetime] = None


class StateTransitionRequest(BaseModel):
    """Request schema for state transition."""

    state: DocumentStatus = Field(..., description="Target state")
    expected_state: Optional[DocumentStatus] = Field(
        None, description="Expected current state for optimistic locking"
    )
    worker_id: str = Field(..., description="ID of the worker making the transition")
    error_message: Optional[str] = Field(
        None, description="Error message (required if state is 'failed')"
    )
    artifact_pointers: Optional[dict[str, str]] = Field(
        None, description="Updated artifact pointers"
    )

    @field_validator("artifact_pointers")
    @classmethod
    def validate_artifact_pointers(cls, v: dict[str, str] | None) -> dict[str, str] | None:
        """Validate artifact pointer keys and values are valid S3 key formats."""
        if v is None:
            return v

        valid_pointer_types = {"pdf", "markdown", "chunks", "embeddings", "graph"}

        for key, value in v.items():
            # Validate pointer type
            if key not in valid_pointer_types:
                raise ValueError(
                    f"Invalid artifact pointer type '{key}'. "
                    f"Must be one of: {', '.join(sorted(valid_pointer_types))}"
                )
            # Validate S3 key format (strip s3:// prefix if present)
            key_to_validate = value
            if key_to_validate.startswith("s3://"):
                # Extract just the key part after bucket name
                parts = key_to_validate[5:].split("/", 1)
                key_to_validate = parts[1] if len(parts) > 1 else ""
            if key_to_validate and not S3_KEY_PATTERN.match(key_to_validate):
                raise ValueError(
                    f"Invalid S3 key format for '{key}': '{value}'. "
                    "S3 keys must start with alphanumeric and contain only "
                    "alphanumeric characters, hyphens, underscores, periods, and forward slashes."
                )
        return v

    @model_validator(mode="after")
    def validate_error_message_required(self) -> "StateTransitionRequest":
        """Ensure error_message is provided when transitioning to failed state."""
        if self.state == DocumentStatus.FAILED and not self.error_message:
            raise ValueError("error_message is required when transitioning to failed state")
        return self


class StateTransitionResponse(BaseModel):
    """Response schema for state transition."""

    document_id: UUID
    previous_state: DocumentStatus
    new_state: DocumentStatus
    success: bool


class ErrorResponse(BaseModel):
    """Standardized error response schema."""

    error_code: str = Field(..., description="Machine-readable error code")
    message: str = Field(..., description="Human-readable error message")
    details: Optional[dict[str, Any]] = Field(
        None, description="Additional error details"
    )
    correlation_id: Optional[str] = Field(
        None, description="Request correlation ID for tracing"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "unhealthy"]
    service: str
    version: str = "0.1.0"


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool
    checks: dict[str, bool] = Field(default_factory=dict)


class DocumentListItem(BaseModel):
    """Response schema for document list items."""

    document_id: UUID
    doi: Optional[str] = None
    content_hash: Optional[str] = None
    title: str
    authors: list[AuthorSchema] = Field(default_factory=list)
    journal: Optional[str] = None
    year: Optional[int] = None
    status: DocumentStatus
    created_at: datetime
    updated_at: datetime


class PaginatedDocumentList(BaseModel):
    """Paginated response with cursor support."""

    items: list[DocumentListItem] = Field(default_factory=list)
    total: int = Field(..., description="Total number of items matching filters")
    limit: int = Field(..., description="Maximum items per page")
    next_cursor: Optional[str] = Field(
        None, description="Cursor to fetch next page (base64-encoded document_id)"
    )
    has_more: bool = Field(..., description="Whether more items exist")
