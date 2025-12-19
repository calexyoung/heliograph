"""Pydantic schemas for Ingestion Service."""

from datetime import datetime
from enum import Enum as PyEnum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from shared.schemas.author import AuthorSchema


class ImportStatus(str, PyEnum):
    """Import record status values."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    DUPLICATE = "duplicate"
    IMPORTED = "imported"


class JobType(str, PyEnum):
    """Ingestion job types."""

    UPLOAD = "upload"
    IMPORT = "import"
    BATCH = "batch"
    SEARCH = "search"


class JobStatus(str, PyEnum):
    """Ingestion job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourceStatus(BaseModel):
    """Status of a search source."""

    source: str
    success: bool
    result_count: int = 0
    error: Optional[str] = None


class SearchResult(BaseModel):
    """Unified search result from any connector."""

    source: str = Field(..., description="Source connector name")
    external_id: str = Field(..., description="External identifier (DOI, arXiv ID, etc.)")
    title: str
    authors: list[AuthorSchema] = Field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    abstract: Optional[str] = None
    journal: Optional[str] = None
    pdf_url: Optional[str] = None
    url: Optional[str] = None  # Link to source page
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: Optional[float] = None

    # Dedup hints
    content_similarity_hash: Optional[str] = None


class SearchRequest(BaseModel):
    """Request for unified search across connectors."""

    query: str = Field(..., min_length=1, description="Search query")
    sources: list[Literal["crossref", "semantic_scholar", "arxiv", "scixplorer"]] = Field(
        default=["crossref", "semantic_scholar", "arxiv"],
        description="Sources to search",
    )
    limit: int = Field(default=10, ge=1, le=100, description="Results per source")
    year_from: Optional[int] = Field(None, description="Filter by year (from)")
    year_to: Optional[int] = Field(None, description="Filter by year (to)")
    include_abstracts: bool = Field(default=True, description="Include abstracts in results")


class SearchResponse(BaseModel):
    """Response from unified search."""

    results: list[SearchResult] = Field(default_factory=list)
    total_by_source: dict[str, int] = Field(default_factory=dict)
    query: str
    total_results: int = 0
    sources_searched: list[str] = Field(default_factory=list)
    source_statuses: dict[str, SourceStatus] = Field(default_factory=dict)
    deduplicated_count: int = 0


class ImportRequest(BaseModel):
    """Request to import a paper from external source."""

    doi: Optional[str] = Field(None, description="Paper DOI")
    arxiv_id: Optional[str] = Field(None, description="arXiv identifier (e.g., 1309.3718)")
    bibcode: Optional[str] = Field(None, description="NASA ADS bibcode")
    url: Optional[str] = Field(None, description="Direct URL to paper page")
    download_pdf: bool = Field(default=True, description="Whether to download PDF")
    metadata_override: Optional[dict[str, Any]] = Field(
        None,
        description="Override fetched metadata",
    )


class ImportResponse(BaseModel):
    """Response from import request."""

    job_id: str
    status: ImportStatus
    document_id: Optional[str] = None
    paper: Optional["SearchResult"] = None
    error: Optional[str] = None


class BatchImportRequest(BaseModel):
    """Request to import multiple papers."""

    items: list[ImportRequest] = Field(..., min_length=1, max_length=100)


class BatchImportResponse(BaseModel):
    """Response from batch import."""

    job_id: UUID
    total_items: int
    status: str


class JobStatusResponse(BaseModel):
    """Response for job status query."""

    job_id: UUID
    job_type: str
    status: str
    progress: dict[str, Any] = Field(default_factory=dict)
    total_items: int = 0
    processed_items: int = 0
    document_ids: list[UUID] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class UploadCompleteRequest(BaseModel):
    """Request to complete an upload and register document."""

    upload_id: UUID
    title: Optional[str] = None
    doi: Optional[str] = None
    authors: list[AuthorSchema] = Field(default_factory=list)
    year: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None


class UploadCompleteResponse(BaseModel):
    """Response from upload completion."""

    job_id: UUID
    upload_id: UUID
    document_id: Optional[UUID] = None
    status: str
    content_hash: Optional[str] = None
    message: str


class IngestionJob(BaseModel):
    """Ingestion job schema."""

    job_id: UUID
    user_id: UUID
    job_type: str
    status: str
    source: Optional[str] = None
    query: Optional[str] = None
    progress: dict[str, Any] = Field(default_factory=dict)
    total_items: int = 0
    processed_items: int = 0
    result_data: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    document_ids: list[UUID] = Field(default_factory=list)
    upload_ids: list[UUID] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ImportRecord(BaseModel):
    """Import record schema."""

    document_id: Optional[UUID] = None
    source: str
    external_id: str
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: list[dict[str, Any]] = Field(default_factory=list)
    year: Optional[int] = None
    journal: Optional[str] = None
    abstract: Optional[str] = None
    pdf_url: Optional[str] = None
    s3_key: Optional[str] = None
    content_hash: Optional[str] = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
