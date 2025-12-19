"""Pydantic schemas for document processing."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    """Processing job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class PipelineStage(str, Enum):
    """Pipeline stages."""

    PDF_PARSING = "pdf_parsing"
    SECTION_SEGMENTATION = "section_segmentation"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    KNOWLEDGE_EXTRACTION = "knowledge_extraction"


class SectionType(str, Enum):
    """Document section types."""

    TITLE = "title"
    ABSTRACT = "abstract"
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    CONCLUSION = "conclusion"
    REFERENCES = "references"
    ACKNOWLEDGMENTS = "acknowledgments"
    APPENDIX = "appendix"
    OTHER = "other"


class ParsedSection(BaseModel):
    """Parsed document section."""

    section_type: SectionType
    title: str | None = None
    text: str
    page_start: int | None = None
    page_end: int | None = None
    char_offset_start: int
    char_offset_end: int


class ParsedReference(BaseModel):
    """Parsed reference from document."""

    reference_number: int | None = None
    raw_text: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    arxiv_id: str | None = None


class ExtractedText(BaseModel):
    """Extracted text from PDF."""

    full_text: str
    sections: list[ParsedSection]
    references: list[ParsedReference]
    page_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """Document chunk."""

    chunk_id: UUID
    document_id: UUID
    sequence_number: int
    text: str
    section: SectionType | None = None
    page_start: int | None = None
    page_end: int | None = None
    char_offset_start: int
    char_offset_end: int
    token_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkWithEmbedding(Chunk):
    """Chunk with embedding vector."""

    embedding: list[float]


class ProcessingJob(BaseModel):
    """Processing job."""

    job_id: UUID
    document_id: UUID
    status: ProcessingStatus
    current_stage: PipelineStage | None = None
    stages_completed: list[PipelineStage] = Field(default_factory=list)
    stage_timings: dict[str, float] = Field(default_factory=dict)
    retry_count: int = 0
    error_message: str | None = None
    worker_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class ProcessingResult(BaseModel):
    """Result of document processing."""

    document_id: UUID
    success: bool
    chunk_count: int = 0
    entity_count: int = 0
    processing_time_seconds: float = 0.0
    stage_timings: dict[str, float] = Field(default_factory=dict)
    error: str | None = None
    artifacts: dict[str, str] = Field(default_factory=dict)  # artifact_name -> s3_key


class ReprocessRequest(BaseModel):
    """Request to reprocess a document."""

    document_id: UUID
    from_stage: PipelineStage | None = None  # Start from specific stage
    force: bool = False  # Force reprocess even if already indexed


class DocumentRegisteredEvent(BaseModel):
    """Event received when document is registered."""

    event_type: str = "DocumentRegistered"
    document_id: UUID
    content_hash: str | None = None
    doi: str | None = None
    title: str
    s3_key: str | None = None
    user_id: UUID
    correlation_id: str
    timestamp: datetime


class DocumentIndexedEvent(BaseModel):
    """Event published when document is indexed."""

    event_type: str = "DocumentIndexed"
    document_id: UUID
    chunk_count: int
    entity_count: int
    processing_time_seconds: float
    correlation_id: str
    timestamp: datetime


class ChunkingConfig(BaseModel):
    """Configuration for chunking."""

    max_tokens: int = 512
    overlap_tokens: int = 50
    respect_section_boundaries: bool = True
    min_chunk_tokens: int = 50
