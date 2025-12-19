"""SQLAlchemy models for Knowledge Extraction service."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class EntityModel(Base):
    """Entity model representing extracted entities."""

    __tablename__ = "entities"

    entity_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(500), nullable=False)
    canonical_name = Column(String(500), nullable=False, index=True)
    entity_type = Column(
        Enum(
            "scientific_concept",
            "method",
            "dataset",
            "instrument",
            "phenomenon",
            "mission",
            "spacecraft",
            "celestial_body",
            "organization",
            "author",
            name="entity_type",
        ),
        nullable=False,
    )
    aliases = Column(ARRAY(String), default=list)
    extra_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    mentions = relationship("EntityMentionModel", back_populates="entity", cascade="all, delete-orphan")
    source_relationships = relationship(
        "RelationshipModel",
        foreign_keys="RelationshipModel.source_entity_id",
        back_populates="source_entity",
    )
    target_relationships = relationship(
        "RelationshipModel",
        foreign_keys="RelationshipModel.target_entity_id",
        back_populates="target_entity",
    )

    __table_args__ = (
        Index("idx_entities_type", "entity_type"),
        Index("idx_entities_canonical_name_type", "canonical_name", "entity_type"),
    )


class EntityMentionModel(Base):
    """Model for entity mentions in document chunks."""

    __tablename__ = "entity_mentions"

    mention_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    chunk_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    text = Column(Text, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    confidence = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    entity = relationship("EntityModel", back_populates="mentions")

    __table_args__ = (
        Index("idx_entity_mentions_document", "document_id"),
        Index("idx_entity_mentions_chunk", "chunk_id"),
    )


class RelationshipModel(Base):
    """Model for relationships between entities."""

    __tablename__ = "relationships"

    relationship_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False)
    target_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.entity_id"), nullable=False)
    relationship_type = Column(
        Enum(
            "cites",
            "authored_by",
            "uses_method",
            "uses_dataset",
            "uses_instrument",
            "studies",
            "mentions",
            "related_to",
            "part_of",
            "causes",
            "observes",
            name="relationship_type",
        ),
        nullable=False,
    )
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    evidence = Column(JSONB, default=list)  # List of EvidencePointer
    extra_metadata = Column("metadata", JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    source_entity = relationship(
        "EntityModel",
        foreign_keys=[source_entity_id],
        back_populates="source_relationships",
    )
    target_entity = relationship(
        "EntityModel",
        foreign_keys=[target_entity_id],
        back_populates="target_relationships",
    )

    __table_args__ = (
        Index("idx_relationships_source", "source_entity_id"),
        Index("idx_relationships_target", "target_entity_id"),
        Index("idx_relationships_document", "document_id"),
        Index("idx_relationships_type", "relationship_type"),
    )


class ExtractionJobModel(Base):
    """Model for extraction jobs."""

    __tablename__ = "extraction_jobs"

    job_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    document_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    status = Column(
        Enum("pending", "in_progress", "completed", "failed", name="extraction_status"),
        nullable=False,
        default="pending",
    )
    entity_count = Column(Integer, default=0)
    relationship_count = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    worker_id = Column(String(100), nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (Index("idx_extraction_jobs_status", "status"),)
