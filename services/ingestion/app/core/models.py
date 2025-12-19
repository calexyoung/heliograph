"""SQLAlchemy models for Ingestion Service."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Database-agnostic types that use JSONB on PostgreSQL and JSON on SQLite
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    pass


class JobType(str, Enum):
    """Ingestion job types."""
    UPLOAD = "upload"
    IMPORT = "import"
    BATCH = "batch"
    SEARCH = "search"


class JobStatus(str, Enum):
    """Ingestion job status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ImportStatus(str, Enum):
    """Import record status."""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionJobModel(Base):
    """SQLAlchemy model for ingestion_jobs table."""

    __tablename__ = "ingestion_jobs"

    job_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    job_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )

    # Job details
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Progress
    progress: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    processed_items: Mapped[int] = mapped_column(Integer, default=0)

    # Results
    result_data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Related entities (stored as JSON for SQLite compatibility)
    document_ids: Mapped[list] = mapped_column(
        JSONType,
        default=list,
    )
    upload_ids: Mapped[list] = mapped_column(
        JSONType,
        default=list,
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    import_records: Mapped[list["ImportRecordModel"]] = relationship(
        "ImportRecordModel",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("idx_ingestion_jobs_user_id", "user_id"),
        Index("idx_ingestion_jobs_status", "status"),
    )


class ImportRecordModel(Base):
    """SQLAlchemy model for import_records table."""

    __tablename__ = "import_records"

    import_id: Mapped[UUID] = mapped_column(
        Uuid,
        primary_key=True,
        default=uuid4,
    )
    job_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("ingestion_jobs.job_id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)

    # Source
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    # Metadata
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    authors: Mapped[list[dict]] = mapped_column(JSONType, default=list)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doi: Mapped[str | None] = mapped_column(String(255), nullable=True)
    journal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    # PDF
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Status
    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Result
    document_id: Mapped[UUID | None] = mapped_column(Uuid, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    job: Mapped["IngestionJobModel"] = relationship(
        "IngestionJobModel",
        back_populates="import_records",
    )

    __table_args__ = (
        Index("idx_import_records_job_id", "job_id"),
        Index("idx_import_records_source_external_id", "source", "external_id", unique=True),
    )
