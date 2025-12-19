"""Pydantic schemas for Query Orchestrator service."""

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class QueryIntent(str, Enum):
    """Types of query intents."""

    SUMMARY = "summary"  # Summarize information about a topic
    COMPARE = "compare"  # Compare two or more things
    FIND_EVIDENCE = "find_evidence"  # Find evidence for a claim
    EXPLORE = "explore"  # Explore related topics
    EXPLAIN = "explain"  # Explain a concept
    LIST = "list"  # List items matching criteria
    FACTUAL = "factual"  # Answer a factual question


class QueryConstraint(BaseModel):
    """Constraints extracted from the query."""

    year_start: int | None = None
    year_end: int | None = None
    authors: list[str] = Field(default_factory=list)
    journals: list[str] = Field(default_factory=list)
    document_ids: list[UUID] = Field(default_factory=list)
    entity_types: list[str] = Field(default_factory=list)


class ParsedQuery(BaseModel):
    """Result of query parsing and understanding."""

    original_query: str
    intent: QueryIntent
    rewritten_query: str | None = None
    entities: list[str] = Field(default_factory=list)
    constraints: QueryConstraint = Field(default_factory=QueryConstraint)
    keywords: list[str] = Field(default_factory=list)


class ChunkEvidence(BaseModel):
    """Evidence from a document chunk."""

    chunk_id: UUID
    document_id: UUID
    text: str
    section: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    similarity_score: float
    rerank_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphPath(BaseModel):
    """A path through the knowledge graph."""

    nodes: list[str]
    edges: list[str]
    confidence: float


class EvidenceMap(BaseModel):
    """Collection of evidence supporting a query."""

    chunks: list[ChunkEvidence]
    graph_paths: list[GraphPath] = Field(default_factory=list)
    total_chunks_retrieved: int = 0
    total_chunks_after_rerank: int = 0


class RetrievalResult(BaseModel):
    """Result of retrieval stage."""

    query: ParsedQuery
    evidence: EvidenceMap
    retrieval_time_ms: float


class QueryRequest(BaseModel):
    """Request to query the RAG system."""

    query: str
    corpus_ids: list[UUID] | None = None  # Limit to specific documents
    max_results: int = Field(default=10, ge=1, le=50)
    include_graph: bool = True
    streaming: bool = False
    conversation_id: UUID | None = None  # For multi-turn conversations


class Citation(BaseModel):
    """A citation in the response."""

    citation_id: int
    chunk_id: UUID
    document_id: UUID
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    page: int | None = None
    section: str | None = None
    snippet: str


class QueryResponse(BaseModel):
    """Response from the RAG system."""

    answer: str
    citations: list[Citation]
    evidence: EvidenceMap
    confidence: float = Field(ge=0.0, le=1.0)
    query_intent: QueryIntent
    processing_time_ms: float


class StreamChunk(BaseModel):
    """A chunk of streaming response."""

    type: str  # "text", "citation", "done"
    content: str | None = None
    citation: Citation | None = None
    evidence_update: list[ChunkEvidence] | None = None


class ConversationMessage(BaseModel):
    """A message in a conversation."""

    role: str  # "user" or "assistant"
    content: str
    citations: list[Citation] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Conversation(BaseModel):
    """A multi-turn conversation."""

    conversation_id: UUID
    messages: list[ConversationMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SearchFilters(BaseModel):
    """Filters for vector search."""

    document_ids: list[str] | None = None
    year_min: int | None = None
    year_max: int | None = None
    sections: list[str] | None = None
    authors: list[str] | None = None
    journals: list[str] | None = None
