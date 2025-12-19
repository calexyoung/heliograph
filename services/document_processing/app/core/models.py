"""Database models for document processing."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship

# Database-agnostic types that use JSONB on PostgreSQL and JSON on SQLite
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class for models."""

    pass


class ChunkModel(Base):
    """Document chunk model."""

    __tablename__ = "document_chunks"

    chunk_id = Column(Uuid, primary_key=True)
    document_id = Column(Uuid, nullable=False, index=True)
    sequence_number = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    section = Column(String(100), nullable=True)
    page_start = Column(Integer, nullable=True)
    page_end = Column(Integer, nullable=True)
    char_offset_start = Column(Integer, nullable=False)
    char_offset_end = Column(Integer, nullable=False)
    token_count = Column(Integer, nullable=False)
    embedding_id = Column(String(255), nullable=True)  # Qdrant point ID
    extra_metadata = Column("metadata", JSONType, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_chunks_document_section", "document_id", "section"),
        Index("idx_chunks_document_sequence", "document_id", "sequence_number"),
    )


class ExtractedEntityModel(Base):
    """Extracted entity model."""

    __tablename__ = "extracted_entities"

    entity_id = Column(Uuid, primary_key=True)
    document_id = Column(Uuid, nullable=False, index=True)
    chunk_id = Column(Uuid, ForeignKey("document_chunks.chunk_id"), nullable=True)
    entity_type = Column(String(50), nullable=False)  # concept, method, dataset, instrument
    name = Column(String(500), nullable=False)
    normalized_name = Column(String(500), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0)
    char_offset_start = Column(Integer, nullable=True)
    char_offset_end = Column(Integer, nullable=True)
    extra_metadata = Column("metadata", JSONType, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_entities_document", "document_id"),
        Index("idx_entities_type_name", "entity_type", "normalized_name"),
    )


class ProcessingJobModel(Base):
    """Processing job model for tracking pipeline execution."""

    __tablename__ = "processing_jobs"

    job_id = Column(Uuid, primary_key=True)
    document_id = Column(Uuid, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="pending")
    current_stage = Column(String(50), nullable=True)
    stages_completed = Column(JSONType, default=list)
    stage_timings = Column(JSONType, default=dict)
    retry_count = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    worker_id = Column(String(100), nullable=True)
    extra_metadata = Column("metadata", JSONType, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_processing_jobs_status", "status"),
        Index("idx_processing_jobs_document", "document_id"),
    )
