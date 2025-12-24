"""Extraction API routes for Knowledge Extraction service."""

import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings, get_settings
from ...core.models import EntityModel, EntityMentionModel, ExtractionJobModel, RelationshipModel
from ...core.schemas import (
    EntityResponse,
    EntityType,
    EvidencePointer,
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
from ..deps import get_db, get_neo4j_client, async_session, engine

logger = structlog.get_logger()

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
    """Run extraction job in background.

    This worker:
    1. Updates job status to in_progress
    2. Fetches document metadata from registry
    3. Fetches chunks from S3 storage
    4. Extracts entities and relationships from each chunk
    5. Stores results in PostgreSQL and Neo4j
    6. Updates job status to completed/failed
    """
    logger.info("extraction_job_started", job_id=str(job_id), document_id=str(document_id))

    # Track results
    all_entities: list[ExtractedEntity] = []
    all_relationships: list[ExtractedRelationship] = []
    total_entity_count = 0
    total_relationship_count = 0
    error_message: str | None = None

    # Create database session for background task
    async with async_session() as db:
        try:
            # Update job status to in_progress
            result = await db.execute(
                select(ExtractionJobModel).where(ExtractionJobModel.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                logger.error("extraction_job_not_found", job_id=str(job_id))
                return

            job.status = "in_progress"
            job.started_at = datetime.utcnow()
            await db.commit()

            # Fetch document metadata from registry
            doc_metadata = await _fetch_document_metadata(document_id, settings)
            if not doc_metadata:
                raise ValueError(f"Document {document_id} not found in registry")

            # Fetch chunks from S3
            chunks = await _fetch_document_chunks(document_id, settings)
            if not chunks:
                raise ValueError(f"No chunks found for document {document_id}")

            # Filter chunks if specific chunk_ids provided
            if chunk_ids:
                chunk_id_strs = {str(cid) for cid in chunk_ids}
                chunks = [c for c in chunks if c.get("chunk_id") in chunk_id_strs]

            logger.info(
                "extraction_chunks_loaded",
                job_id=str(job_id),
                chunk_count=len(chunks),
            )

            # Initialize extractors
            entity_extractor = EntityExtractor(settings)
            relationship_extractor = RelationshipExtractor(settings)
            normalizer = EntityNormalizer()

            # Initialize Neo4j client
            neo4j = Neo4jClient(settings)
            await neo4j.connect()

            try:
                # Ensure article node exists in Neo4j
                await neo4j.upsert_article(
                    document_id=document_id,
                    title=doc_metadata.get("title", f"Document {document_id}"),
                    year=doc_metadata.get("year"),
                    doi=doc_metadata.get("doi"),
                    authors=[a.get("name", "") for a in doc_metadata.get("authors", [])],
                )

                # Process each chunk
                for i, chunk in enumerate(chunks):
                    chunk_id = UUID(chunk["chunk_id"])
                    chunk_text = chunk.get("text", "")

                    if not chunk_text or len(chunk_text) < 50:
                        continue

                    logger.debug(
                        "processing_chunk",
                        job_id=str(job_id),
                        chunk_index=i,
                        chunk_id=str(chunk_id),
                        text_length=len(chunk_text),
                    )

                    try:
                        # Extract entities
                        entities = await entity_extractor.extract_entities(
                            chunk_text, chunk_id, document_id
                        )
                        entities = [normalizer.normalize(e) for e in entities]
                        entities = normalizer.deduplicate(entities)

                        # Extract relationships
                        relationships = await relationship_extractor.extract_relationships(
                            chunk_text, entities, chunk_id, document_id
                        )

                        # Store entities in Neo4j
                        for entity in entities:
                            await neo4j.upsert_entity(entity)
                            await neo4j.create_mention_relationship(
                                document_id=document_id,
                                entity=entity,
                                chunk_id=chunk_id,
                                confidence=entity.confidence,
                            )

                            # Store in PostgreSQL
                            await _store_entity_in_postgres(db, entity, chunk_id, document_id)

                        # Store relationships in Neo4j
                        entity_map = {e.name.lower(): e for e in entities}
                        for rel in relationships:
                            source = entity_map.get(rel.source_entity.lower())
                            target = entity_map.get(rel.target_entity.lower())
                            if source and target:
                                await neo4j.create_relationship(rel, source, target)
                                await _store_relationship_in_postgres(db, rel, source, target, document_id)

                        all_entities.extend(entities)
                        all_relationships.extend(relationships)
                        total_entity_count += len(entities)
                        total_relationship_count += len(relationships)

                    except Exception as e:
                        logger.warning(
                            "chunk_extraction_failed",
                            job_id=str(job_id),
                            chunk_id=str(chunk_id),
                            error=str(e),
                        )
                        # Rollback to recover from database errors
                        await db.rollback()
                        continue

                    # Commit after each chunk to avoid large transactions
                    await db.commit()

            finally:
                await entity_extractor.close()
                await relationship_extractor.close()
                await neo4j.close()

            # Update job as completed
            job.status = "completed"
            job.entity_count = total_entity_count
            job.relationship_count = total_relationship_count
            job.completed_at = datetime.utcnow()
            await db.commit()

            logger.info(
                "extraction_job_completed",
                job_id=str(job_id),
                document_id=str(document_id),
                entity_count=total_entity_count,
                relationship_count=total_relationship_count,
            )

        except Exception as e:
            error_message = str(e)
            logger.error(
                "extraction_job_failed",
                job_id=str(job_id),
                document_id=str(document_id),
                error=error_message,
            )

            # Update job as failed
            try:
                result = await db.execute(
                    select(ExtractionJobModel).where(ExtractionJobModel.job_id == job_id)
                )
                job = result.scalar_one_or_none()
                if job:
                    job.status = "failed"
                    job.error_message = error_message
                    job.completed_at = datetime.utcnow()
                    await db.commit()
            except Exception as commit_error:
                logger.error("failed_to_update_job_status", error=str(commit_error))


async def _fetch_document_metadata(document_id: UUID, settings: Settings) -> dict | None:
    """Fetch document metadata from the document registry."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.DOCUMENT_REGISTRY_URL}/registry/documents/{document_id}"
            )
            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                logger.warning("document_not_found", document_id=str(document_id))
                return None
            else:
                logger.error(
                    "registry_request_failed",
                    document_id=str(document_id),
                    status_code=response.status_code,
                )
                return None
    except Exception as e:
        logger.error("registry_request_error", document_id=str(document_id), error=str(e))
        return None


async def _fetch_document_chunks(document_id: UUID, settings: Settings) -> list[dict]:
    """Fetch document chunks from S3 storage."""
    try:
        # Import storage client
        from shared.utils.s3 import S3Client

        storage = S3Client(
            bucket=settings.S3_BUCKET,
            endpoint_url=settings.S3_ENDPOINT_URL,
        )

        # Chunks are stored at documents/{document_id}/artifacts/chunks.json
        chunks_key = f"documents/{document_id}/artifacts/chunks.json"

        try:
            chunks_data = await storage.download_object(chunks_key)
            chunks = json.loads(chunks_data.decode("utf-8"))
            return chunks if isinstance(chunks, list) else []
        except Exception as e:
            logger.warning("chunks_not_found", document_id=str(document_id), error=str(e))
            return []

    except Exception as e:
        logger.error("storage_error", document_id=str(document_id), error=str(e))
        return []


async def _store_entity_in_postgres(
    db: AsyncSession,
    entity: ExtractedEntity,
    chunk_id: UUID,
    document_id: UUID,
) -> None:
    """Store an entity and its mention in PostgreSQL."""
    # Check if entity already exists
    result = await db.execute(
        select(EntityModel).where(
            EntityModel.canonical_name == entity.canonical_name,
            EntityModel.entity_type == entity.entity_type.value,
        )
    )
    existing_entity = result.scalar_one_or_none()

    if existing_entity:
        # Update aliases if needed
        current_aliases = set(existing_entity.aliases or [])
        new_aliases = set(entity.aliases or [])
        if new_aliases - current_aliases:
            existing_entity.aliases = list(current_aliases | new_aliases)
        entity_id = existing_entity.entity_id
    else:
        # Create new entity
        db_entity = EntityModel(
            entity_id=entity.entity_id,
            name=entity.name,
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type.value,
            aliases=entity.aliases,
        )
        db.add(db_entity)
        await db.flush()
        entity_id = db_entity.entity_id

    # Create mentions from the entity's mention list
    for mention_data in entity.mentions:
        mention = EntityMentionModel(
            entity_id=entity_id,
            document_id=document_id,
            chunk_id=mention_data.chunk_id,
            text=mention_data.text,
            char_start=mention_data.char_start,
            char_end=mention_data.char_end,
            confidence=mention_data.confidence,
        )
        db.add(mention)

    # If no mentions, create a default one with the chunk_id
    if not entity.mentions:
        mention = EntityMentionModel(
            entity_id=entity_id,
            document_id=document_id,
            chunk_id=chunk_id,
            text=entity.name,  # Use entity name as text when no specific mention
            char_start=0,
            char_end=len(entity.name),
            confidence=entity.confidence,
        )
        db.add(mention)


async def _store_relationship_in_postgres(
    db: AsyncSession,
    relationship: ExtractedRelationship,
    source_entity: ExtractedEntity,
    target_entity: ExtractedEntity,
    document_id: UUID,
) -> None:
    """Store a relationship in PostgreSQL."""
    # Get entity IDs from database
    source_result = await db.execute(
        select(EntityModel).where(
            EntityModel.canonical_name == source_entity.canonical_name,
            EntityModel.entity_type == source_entity.entity_type.value,
        )
    )
    source_db = source_result.scalar_one_or_none()

    target_result = await db.execute(
        select(EntityModel).where(
            EntityModel.canonical_name == target_entity.canonical_name,
            EntityModel.entity_type == target_entity.entity_type.value,
        )
    )
    target_db = target_result.scalar_one_or_none()

    if not source_db or not target_db:
        return

    # Check if relationship exists
    existing = await db.execute(
        select(RelationshipModel).where(
            RelationshipModel.source_entity_id == source_db.entity_id,
            RelationshipModel.target_entity_id == target_db.entity_id,
            RelationshipModel.relationship_type == relationship.relationship_type.value,
        )
    )
    existing_rel = existing.scalar_one_or_none()

    if existing_rel:
        # Update confidence if higher
        if relationship.confidence > existing_rel.confidence:
            existing_rel.confidence = relationship.confidence
        # Add new evidence
        current_evidence = existing_rel.evidence or []
        new_evidence = [
            {
                "chunk_id": str(e.chunk_id),
                "document_id": str(e.document_id),
                "char_start": e.char_start,
                "char_end": e.char_end,
                "snippet": e.snippet,
            }
            for e in relationship.evidence
        ]
        existing_rel.evidence = current_evidence + new_evidence
    else:
        # Create new relationship
        db_rel = RelationshipModel(
            source_entity_id=source_db.entity_id,
            target_entity_id=target_db.entity_id,
            relationship_type=relationship.relationship_type.value,
            document_id=document_id,
            confidence=relationship.confidence,
            evidence=[
                {
                    "chunk_id": str(e.chunk_id),
                    "document_id": str(e.document_id),
                    "char_start": e.char_start,
                    "char_end": e.char_end,
                    "snippet": e.snippet,
                }
                for e in relationship.evidence
            ],
        )
        db.add(db_rel)
