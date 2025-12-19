"""Chunk retrieval API endpoints."""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_processing.app.api.deps import get_db, get_qdrant_client, get_embedding_generator
from services.document_processing.app.core.models import ChunkModel
from services.document_processing.app.core.schemas import Chunk, SectionType
from services.document_processing.app.embeddings.generator import EmbeddingGenerator
from services.document_processing.app.embeddings.qdrant import QdrantClient
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()


@router.get("/document/{document_id}", response_model=list[Chunk])
async def get_document_chunks(
    document_id: UUID,
    section: SectionType | None = Query(None, description="Filter by section"),
    db: AsyncSession = Depends(get_db),
):
    """Get all chunks for a document."""
    query = select(ChunkModel).where(ChunkModel.document_id == document_id)

    if section:
        query = query.where(ChunkModel.section == section.value)

    query = query.order_by(ChunkModel.sequence_number)

    result = await db.execute(query)
    chunks = result.scalars().all()

    return [
        Chunk(
            chunk_id=c.chunk_id,
            document_id=c.document_id,
            sequence_number=c.sequence_number,
            text=c.text,
            section=SectionType(c.section) if c.section else None,
            page_start=c.page_start,
            page_end=c.page_end,
            char_offset_start=c.char_offset_start,
            char_offset_end=c.char_offset_end,
            token_count=c.token_count,
            metadata=c.metadata or {},
        )
        for c in chunks
    ]


@router.get("/{chunk_id}", response_model=Chunk)
async def get_chunk(
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific chunk by ID."""
    result = await db.execute(
        select(ChunkModel).where(ChunkModel.chunk_id == chunk_id)
    )
    chunk = result.scalar_one_or_none()

    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")

    return Chunk(
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        sequence_number=chunk.sequence_number,
        text=chunk.text,
        section=SectionType(chunk.section) if chunk.section else None,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        char_offset_start=chunk.char_offset_start,
        char_offset_end=chunk.char_offset_end,
        token_count=chunk.token_count,
        metadata=chunk.metadata or {},
    )


@router.post("/search")
async def search_chunks(
    query: str,
    limit: int = Query(10, ge=1, le=100),
    document_ids: list[UUID] | None = Query(None, description="Limit to specific documents"),
    section: SectionType | None = Query(None, description="Filter by section"),
    year_from: int | None = Query(None, description="Filter from year"),
    year_to: int | None = Query(None, description="Filter to year"),
    score_threshold: float | None = Query(None, ge=0, le=1, description="Minimum similarity score"),
    embedding_generator: EmbeddingGenerator = Depends(get_embedding_generator),
    qdrant: QdrantClient = Depends(get_qdrant_client),
):
    """Search for chunks using semantic similarity.

    Returns chunks ranked by similarity to the query.
    """
    # Generate query embedding
    query_embedding = await embedding_generator.generate_single(query)

    # Build filters
    filters = {}
    if document_ids:
        filters["document_ids"] = document_ids
    if section:
        filters["section"] = section.value
    if year_from:
        filters["year_from"] = year_from
    if year_to:
        filters["year_to"] = year_to

    # Search Qdrant
    results = await qdrant.search(
        query_vector=query_embedding,
        limit=limit,
        filters=filters if filters else None,
        score_threshold=score_threshold,
    )

    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


@router.get("/search/text")
async def search_chunks_get(
    query: str = Query(..., description="Search query"),
    limit: int = Query(10, ge=1, le=100),
    document_id: UUID | None = Query(None, description="Limit to specific document"),
    embedding_generator: EmbeddingGenerator = Depends(get_embedding_generator),
    qdrant: QdrantClient = Depends(get_qdrant_client),
):
    """Search for chunks (GET endpoint for simple queries)."""
    # Generate query embedding
    query_embedding = await embedding_generator.generate_single(query)

    # Build filters
    filters = {}
    if document_id:
        filters["document_id"] = document_id

    # Search Qdrant
    results = await qdrant.search(
        query_vector=query_embedding,
        limit=limit,
        filters=filters if filters else None,
    )

    return {
        "query": query,
        "results": results,
        "count": len(results),
    }


@router.delete("/document/{document_id}")
async def delete_document_chunks(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
    qdrant: QdrantClient = Depends(get_qdrant_client),
):
    """Delete all chunks for a document.

    Removes from both database and Qdrant.
    """
    # Delete from Qdrant
    await qdrant.delete_by_document(document_id)

    # Delete from database
    result = await db.execute(
        select(ChunkModel).where(ChunkModel.document_id == document_id)
    )
    chunks = result.scalars().all()

    for chunk in chunks:
        await db.delete(chunk)

    await db.commit()

    return {
        "deleted": True,
        "document_id": str(document_id),
        "chunks_deleted": len(chunks),
    }


@router.get("/collection/info")
async def get_collection_info(
    qdrant: QdrantClient = Depends(get_qdrant_client),
):
    """Get Qdrant collection information."""
    return await qdrant.get_collection_info()
