"""Pydantic schemas for Knowledge Extraction service."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Types of entities that can be extracted."""

    SCIENTIFIC_CONCEPT = "scientific_concept"
    METHOD = "method"
    DATASET = "dataset"
    INSTRUMENT = "instrument"
    PHENOMENON = "phenomenon"
    MISSION = "mission"
    SPACECRAFT = "spacecraft"
    CELESTIAL_BODY = "celestial_body"
    ORGANIZATION = "organization"
    AUTHOR = "author"


class RelationshipType(str, Enum):
    """Types of relationships between entities."""

    CITES = "cites"
    AUTHORED_BY = "authored_by"
    USES_METHOD = "uses_method"
    USES_DATASET = "uses_dataset"
    USES_INSTRUMENT = "uses_instrument"
    STUDIES = "studies"
    MENTIONS = "mentions"
    RELATED_TO = "related_to"
    PART_OF = "part_of"
    CAUSES = "causes"
    OBSERVES = "observes"


class ExtractionStatus(str, Enum):
    """Status of extraction job."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


# Entity schemas
class EntityMention(BaseModel):
    """A mention of an entity in text."""

    chunk_id: UUID
    text: str
    char_start: int
    char_end: int
    confidence: float = Field(ge=0.0, le=1.0)


class ExtractedEntity(BaseModel):
    """An entity extracted from a document."""

    entity_id: UUID | None = None
    name: str
    canonical_name: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)
    mentions: list[EntityMention] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityCreate(BaseModel):
    """Schema for creating an entity."""

    name: str
    canonical_name: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    aliases: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityResponse(BaseModel):
    """Entity response schema."""

    entity_id: UUID
    name: str
    canonical_name: str
    entity_type: EntityType
    aliases: list[str]
    document_count: int = 0
    mention_count: int = 0
    created_at: datetime
    updated_at: datetime


# Relationship schemas
class EvidencePointer(BaseModel):
    """Pointer to evidence for a relationship."""

    chunk_id: UUID
    document_id: UUID
    char_start: int
    char_end: int
    snippet: str


class ExtractedRelationship(BaseModel):
    """A relationship extracted from a document."""

    relationship_id: UUID | None = None
    source_entity: str  # Entity name or ID
    target_entity: str  # Entity name or ID
    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidencePointer] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipCreate(BaseModel):
    """Schema for creating a relationship."""

    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    document_id: UUID
    evidence: list[EvidencePointer] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RelationshipResponse(BaseModel):
    """Relationship response schema."""

    relationship_id: UUID
    source_entity_id: UUID
    target_entity_id: UUID
    relationship_type: RelationshipType
    confidence: float
    document_id: UUID
    created_at: datetime


# Graph schemas
class GraphNode(BaseModel):
    """A node in the knowledge graph."""

    node_id: str
    entity_id: UUID | None = None
    document_id: UUID | None = None
    label: str
    node_type: str  # "entity" or "article"
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """An edge in the knowledge graph."""

    edge_id: str
    source_id: str
    target_id: str
    relationship_type: str
    confidence: float
    properties: dict[str, Any] = Field(default_factory=dict)


class SubgraphRequest(BaseModel):
    """Request for a subgraph."""

    center_node_id: str
    depth: int = Field(ge=1, le=5, default=2)
    node_types: list[str] | None = None
    edge_types: list[str] | None = None
    min_confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    max_nodes: int = Field(ge=1, le=500, default=100)


class SubgraphResponse(BaseModel):
    """Response containing a subgraph."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]
    center_node: GraphNode | None = None
    evidence_refs: dict[str, list[EvidencePointer]] = Field(default_factory=dict)


class GraphSearchRequest(BaseModel):
    """Request to search the graph."""

    query: str
    node_type: str | None = None
    limit: int = Field(ge=1, le=100, default=20)


class GraphSearchResult(BaseModel):
    """Result of a graph search."""

    node: GraphNode
    score: float
    matched_text: str


# Extraction job schemas
class ExtractionJobCreate(BaseModel):
    """Schema for creating an extraction job."""

    document_id: UUID
    chunk_ids: list[UUID] | None = None  # If None, extract from all chunks


class ExtractionJobResponse(BaseModel):
    """Response for an extraction job."""

    job_id: UUID
    document_id: UUID
    status: ExtractionStatus
    entity_count: int = 0
    relationship_count: int = 0
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ExtractionResult(BaseModel):
    """Result of entity and relationship extraction."""

    document_id: UUID
    entities: list[ExtractedEntity]
    relationships: list[ExtractedRelationship]
    processing_time_seconds: float


# Document event schema
class DocumentIndexedEvent(BaseModel):
    """Event received when a document has been indexed."""

    event_type: str = "DocumentIndexed"
    document_id: UUID
    chunk_count: int
    entity_count: int
    processing_time_seconds: float
    correlation_id: str
    timestamp: datetime
