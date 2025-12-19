"""SQLAlchemy models for Document Registry."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from shared.schemas.document import DocumentStatus


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""

    pass


class DocumentModel(Base):
    """SQLAlchemy model for registry_documents table."""

    __tablename__ = "registry_documents"

    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    doi: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str | None] = mapped_column(Text, nullable=True)
    journal: Mapped[str | None] = mapped_column(String(500), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda x: [e.value for e in x]),
        default=DocumentStatus.REGISTERED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_pointers: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
    last_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    # Relationships
    provenance_records: Mapped[list["ProvenanceModel"]] = relationship(
        "ProvenanceModel",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    state_audit_records: Mapped[list["StateAuditModel"]] = relationship(
        "StateAuditModel",
        back_populates="document",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_content_hash"),
        UniqueConstraint("content_hash", "title_normalized", "year", name="uq_content_title_year"),
        Index("idx_registry_documents_status", "status"),
        Index("idx_registry_documents_content_hash", "content_hash"),
        Index("idx_registry_documents_created_at", "created_at"),
        Index("idx_registry_documents_composite", "content_hash", "title_normalized", "year"),
    )


class ProvenanceModel(Base):
    """SQLAlchemy model for document_provenance table."""

    __tablename__ = "document_provenance"

    provenance_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("registry_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    connector_job_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    upload_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    user_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    document: Mapped["DocumentModel"] = relationship(
        "DocumentModel",
        back_populates="provenance_records",
    )

    __table_args__ = (
        Index("idx_document_provenance_document_id", "document_id"),
        Index("idx_document_provenance_user_id", "user_id"),
    )


class StateAuditModel(Base):
    """SQLAlchemy model for document_state_audit table."""

    __tablename__ = "document_state_audit"

    audit_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    document_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("registry_documents.document_id", ondelete="CASCADE"),
        nullable=False,
    )
    previous_state: Mapped[DocumentStatus | None] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda x: [e.value for e in x]),
        nullable=True,
    )
    new_state: Mapped[DocumentStatus] = mapped_column(
        Enum(DocumentStatus, name="document_status", values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    document: Mapped["DocumentModel"] = relationship(
        "DocumentModel",
        back_populates="state_audit_records",
    )

    __table_args__ = (
        Index("idx_state_audit_document_id", "document_id"),
        Index("idx_state_audit_created_at", "created_at"),
    )
