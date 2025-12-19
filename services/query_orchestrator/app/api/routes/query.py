"""Query API routes for the Query Orchestrator service."""

from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...config import Settings, get_settings
from ...core.orchestrator import QueryOrchestrator
from ...core.schemas import (
    ChunkEvidence,
    Citation,
    ParsedQuery,
    QueryRequest,
    QueryResponse,
    StreamChunk,
)

router = APIRouter(prefix="/query", tags=["query"])

# Global orchestrator instance
_orchestrator: QueryOrchestrator | None = None


async def get_orchestrator(settings: Settings = Depends(get_settings)) -> QueryOrchestrator:
    """Get the query orchestrator instance."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = QueryOrchestrator(settings)
        await _orchestrator.initialize()
    return _orchestrator


@router.post("", response_model=QueryResponse)
async def query(
    request: QueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> QueryResponse:
    """Query the RAG system.

    Processes a natural language query through the full RAG pipeline:
    1. Query understanding and parsing
    2. Vector retrieval from Qdrant
    3. Graph-augmented retrieval from Neo4j
    4. Re-ranking and context assembly
    5. LLM generation with citations

    Returns an answer with citations and supporting evidence.
    """
    try:
        return await orchestrator.query(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def query_stream(
    request: QueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> StreamingResponse:
    """Query the RAG system with streaming response.

    Returns a server-sent events stream with:
    - evidence: Initial evidence chunks found
    - text: Generated text chunks
    - citation: Citation markers as they're referenced
    - done: End of stream marker
    """
    request.streaming = True

    async def generate() -> AsyncIterator[str]:
        async for chunk in orchestrator.query_stream(request):
            import json
            yield f"data: {json.dumps(chunk.model_dump())}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


class ParseQueryRequest(BaseModel):
    """Request to parse a query."""

    query: str


@router.post("/parse", response_model=ParsedQuery)
async def parse_query(
    request: ParseQueryRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> ParsedQuery:
    """Parse a query without running the full pipeline.

    Useful for debugging query understanding and for
    building query suggestions in the UI.
    """
    return orchestrator.query_parser.parse(request.query)


class RetrieveRequest(BaseModel):
    """Request to retrieve without generation."""

    query: str
    corpus_ids: list[UUID] | None = None
    max_results: int = 10
    include_graph: bool = True


class RetrieveResponse(BaseModel):
    """Response from retrieval only."""

    chunks: list[ChunkEvidence]
    parsed_query: ParsedQuery


@router.post("/retrieve", response_model=RetrieveResponse)
async def retrieve_only(
    request: RetrieveRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> RetrieveResponse:
    """Retrieve relevant chunks without LLM generation.

    Useful for:
    - Testing retrieval quality
    - Building search interfaces
    - Pre-fetching context for custom generation
    """
    from ...core.schemas import QueryRequest

    query_request = QueryRequest(
        query=request.query,
        corpus_ids=request.corpus_ids,
        max_results=request.max_results,
        include_graph=request.include_graph,
    )

    parsed_query = orchestrator.query_parser.parse(request.query)
    result = await orchestrator._retrieve(parsed_query, query_request)

    return RetrieveResponse(
        chunks=result.evidence.chunks,
        parsed_query=parsed_query,
    )


class SimilarDocumentsRequest(BaseModel):
    """Request for similar documents."""

    document_id: UUID
    max_results: int = 10


class SimilarDocument(BaseModel):
    """A similar document."""

    document_id: UUID
    title: str | None = None
    similarity_reason: str
    score: float


@router.post("/similar", response_model=list[SimilarDocument])
async def find_similar_documents(
    request: SimilarDocumentsRequest,
    orchestrator: QueryOrchestrator = Depends(get_orchestrator),
) -> list[SimilarDocument]:
    """Find documents similar to a given document.

    Uses both vector similarity and graph relationships
    to find related documents.
    """
    # Get related documents from graph
    related = await orchestrator.graph_retriever.find_related_by_entities(
        request.document_id,
        min_shared=1,
    )

    results = []
    for doc in related[:request.max_results]:
        shared = doc.get("shared_entities", [])
        results.append(
            SimilarDocument(
                document_id=UUID(doc["document_id"]),
                title=doc.get("title"),
                similarity_reason=f"Shares entities: {', '.join(shared[:3])}",
                score=len(shared) / 10.0,  # Normalize score
            )
        )

    return results
