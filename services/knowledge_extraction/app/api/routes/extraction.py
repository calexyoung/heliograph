"""Extraction API routes for Knowledge Extraction service."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings, get_settings
from ...core.models import EntityModel, EntityMentionModel, ExtractionJobModel, RelationshipModel
from ...core.schemas import (
    EntityResponse,
    ExtractionJobCreate,
    ExtractionJobResponse,
    ExtractionResult,
    ExtractionStatus,
    ExtractedEntity,
    ExtractedRelationship,
)
from ...extractors.entity_extractor import EntityExtractor, EntityNormalizer
from ...extractors.relationship_extractor import RelationshipExtractor
from ...graph.neo4j_client import Neo4jClient
from ..deps import get_db, get_neo4j_client

router = APIRouter(prefix="/extraction", tags=["extraction"])


@router.post("/jobs", response_model=ExtractionJobResponse)
async def create_extraction_job(
    request: ExtractionJobCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExtractionJobResponse:
    """Create a new extraction job for a document."""
    job = ExtractionJobModel(
        job_id=uuid4(),
        document_id=request.document_id,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Start extraction in background
    background_tasks.add_task(
        run_extraction_job,
        job.job_id,
        request.document_id,
        request.chunk_ids,
        settings,
    )

    return ExtractionJobResponse(
        job_id=job.job_id,
        document_id=job.document_id,
        status=ExtractionStatus(job.status),
        created_at=job.created_at,
    )


@router.get("/jobs/{job_id}", response_model=ExtractionJobResponse)
async def get_extraction_job(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> ExtractionJobResponse:
    """Get extraction job status."""
    result = await db.execute(
        select(ExtractionJobModel).where(ExtractionJobModel.job_id == job_id)
    )
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ExtractionJobResponse(
        job_id=job.job_id,
        document_id=job.document_id,
        status=ExtractionStatus(job.status),
        entity_count=job.entity_count,
        relationship_count=job.relationship_count,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
    )


@router.get("/documents/{document_id}/entities", response_model=list[EntityResponse])
async def get_document_entities(
    document_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> list[EntityResponse]:
    """Get all entities extracted from a document."""
    result = await db.execute(
        select(EntityModel)
        .join(EntityMentionModel)
        .where(EntityMentionModel.document_id == document_id)
        .distinct()
    )
    entities = result.scalars().all()

    return [
        EntityResponse(
            entity_id=e.entity_id,
            name=e.name,
            canonical_name=e.canonical_name,
            entity_type=e.entity_type,
            aliases=e.aliases or [],
            created_at=e.created_at,
            updated_at=e.updated_at,
        )
        for e in entities
    ]


@router.post("/extract", response_model=ExtractionResult)
async def extract_from_text(
    text: str,
    document_id: UUID,
    chunk_id: UUID,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> ExtractionResult:
    """Extract entities and relationships from provided text.

    Supports multiple extraction backends:
    - Custom extractors (default): Two-step entity + relationship extraction
    - LangChain LLMGraphTransformer: Single-pass extraction with constraints
    - Hybrid: LangChain extraction + custom normalization

    Set USE_LANGCHAIN_EXTRACTOR=true or USE_HYBRID_EXTRACTOR=true to switch.
    """
    import time

    start_time = time.time()

    # Select extraction method based on settings
    if settings.USE_HYBRID_EXTRACTOR:
        # Hybrid: LangChain extraction with custom normalization
        from ...extractors.langchain_extractor import HybridExtractor

        extractor = HybridExtractor(settings)
        entities, relationships = await extractor.extract(text, chunk_id, document_id)

    elif settings.USE_LANGCHAIN_EXTRACTOR:
        # Pure LangChain extraction
        from ...extractors.langchain_extractor import LangChainGraphExtractor

        extractor = LangChainGraphExtractor(settings)
        entities, relationships = await extractor.extract(text, chunk_id, document_id)

    else:
        # Default: Custom two-step extraction
        entity_extractor = EntityExtractor(settings)
        relationship_extractor = RelationshipExtractor(settings)
        normalizer = EntityNormalizer()

        try:
            # Extract entities
            entities = await entity_extractor.extract_entities(text, chunk_id, document_id)
            entities = [normalizer.normalize(e) for e in entities]
            entities = normalizer.deduplicate(entities)

            # Extract relationships
            relationships = await relationship_extractor.extract_relationships(
                text, entities, chunk_id, document_id
            )
        finally:
            await entity_extractor.close()
            await relationship_extractor.close()

    # Store entities and relationships in Neo4j
    try:
        # First, ensure the Article node exists
        await neo4j.upsert_article(
            document_id=document_id,
            title=f"Document {document_id}",  # Will be updated with full metadata later
        )

        for entity in entities:
            await neo4j.upsert_entity(entity)
            # Create mention relationship between document and entity
            await neo4j.create_mention_relationship(
                document_id=document_id,
                entity=entity,
                chunk_id=chunk_id,
                confidence=entity.confidence,
            )

        # Create entity-to-entity relationships
        entity_map = {e.name.lower(): e for e in entities}
        for rel in relationships:
            source = entity_map.get(rel.source_entity.lower())
            target = entity_map.get(rel.target_entity.lower())
            if source and target:
                await neo4j.create_relationship(rel, source, target)

    except Exception as e:
        # Log but don't fail - extraction itself succeeded
        import structlog
        logger = structlog.get_logger()
        logger.warning("neo4j_storage_failed", error=str(e))

    processing_time = time.time() - start_time

    return ExtractionResult(
        document_id=document_id,
        entities=entities,
        relationships=relationships,
        processing_time_seconds=processing_time,
    )


async def run_extraction_job(
    job_id: UUID,
    document_id: UUID,
    chunk_ids: list[UUID] | None,
    settings: Settings,
) -> None:
    """Run extraction job in background."""
    # This would be implemented with proper database session management
    # and would fetch chunks from the document processing service
    pass
