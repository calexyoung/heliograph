"""Document schema models."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from shared.schemas.author import AuthorSchema


class DocumentStatus(str, Enum):
    """Document processing status."""

    REGISTERED = "registered"
    PROCESSING = "processing"
    INDEXED = "indexed"
    FAILED = "failed"


class DocumentSource(str, Enum):
    """Document ingestion source."""

    UPLOAD = "upload"
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    ARXIV = "arxiv"
    SCIXPLORER = "scixplorer"


class ProvenanceEntry(BaseModel):
    """Record of document provenance/origin."""

    provenance_id: UUID
    source: DocumentSource
    source_query: Optional[str] = None
    source_identifier: Optional[str] = None
    connector_job_id: Optional[UUID] = None
    upload_id: Optional[UUID] = None
    user_id: UUID
    metadata_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DocumentMetadata(BaseModel):
    """Core document metadata."""

    document_id: UUID
    doi: Optional[str] = None
    content_hash: str = Field(..., description="SHA-256 hash of PDF content")
    title: str
    title_normalized: str
    subtitle: Optional[str] = None
    journal: Optional[str] = None
    year: Optional[int] = None
    authors: list[AuthorSchema] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    status: DocumentStatus = DocumentStatus.REGISTERED
    error_message: Optional[str] = None
    artifact_pointers: dict[str, str] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    last_processed_at: Optional[datetime] = None


class DocumentDetailResponse(BaseModel):
    """Full document detail response including provenance."""

    document_id: UUID
    doi: Optional[str] = None
    content_hash: str
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
