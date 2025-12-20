"""Pipeline orchestrator for document processing."""

import asyncio
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from services.document_processing.app.config import settings
from services.document_processing.app.core.models import ChunkModel, ProcessingJobModel
from services.document_processing.app.core.schemas import (
    Chunk,
    ChunkWithEmbedding,
    DocumentIndexedEvent,
    DocumentRegisteredEvent,
    ExtractedText,
    PipelineStage,
    ProcessingResult,
    ProcessingStatus,
)
from services.document_processing.app.embeddings.generator import EmbeddingGenerator
from services.document_processing.app.embeddings.qdrant import QdrantClient
from services.document_processing.app.parsers.chunker import ChunkingService
from services.document_processing.app.parsers.factory import ParserFactory
from services.document_processing.app.parsers.segmenter import SectionSegmenter
from shared.utils.logging import get_logger
from shared.utils.s3 import StorageClient, get_storage_client
from shared.utils.sqs import SQSClient

logger = get_logger(__name__)


class PipelineOrchestrator:
    """Orchestrate the document processing pipeline."""

    def __init__(
        self,
        db: AsyncSession,
        storage_client: StorageClient | None = None,
        sqs_client: SQSClient | None = None,
    ):
        """Initialize pipeline orchestrator.

        Args:
            db: Database session
            storage_client: Storage client (S3 or local)
            sqs_client: SQS client
        """
        self.db = db
        self.storage_client = storage_client or get_storage_client(
            storage_type=settings.STORAGE_TYPE,
            bucket=settings.S3_BUCKET,
            region=settings.AWS_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL,
            access_key=settings.AWS_ACCESS_KEY_ID,
            secret_key=settings.AWS_SECRET_ACCESS_KEY,
            local_path=settings.LOCAL_STORAGE_PATH,
        )
        self.sqs_client = sqs_client

        # Initialize pipeline components
        self.parser_factory = ParserFactory(
            docling_enabled=settings.DOCLING_ENABLED,
            prefer_grobid_for_scientific=True,  # Prefer GROBID for scientific PDFs when available
        )
        self.segmenter = SectionSegmenter()
        self.chunker = ChunkingService(
            max_tokens=settings.CHUNK_MAX_TOKENS,
            overlap_tokens=settings.CHUNK_OVERLAP_TOKENS,
            respect_sections=settings.CHUNK_RESPECT_SECTIONS,
        )
        self.embedding_generator = EmbeddingGenerator(
            provider=settings.EMBEDDING_PROVIDER,
            model_name=settings.EMBEDDING_MODEL,
            openai_api_key=settings.OPENAI_API_KEY,
        )
        self.qdrant_client = QdrantClient(
            url=settings.QDRANT_URL,
            api_key=settings.QDRANT_API_KEY,
            collection_name=settings.QDRANT_COLLECTION,
        )

    async def process_document(
        self,
        event: DocumentRegisteredEvent,
        worker_id: str,
    ) -> ProcessingResult:
        """Process a registered document through the pipeline.

        Args:
            event: Document registered event
            worker_id: ID of the worker processing this document

        Returns:
            Processing result
        """
        document_id = event.document_id
        start_time = time.time()
        stage_timings: dict[str, float] = {}
        artifacts: dict[str, str] = {}

        # Use event-specific storage config if provided, otherwise use default
        original_storage_client = self.storage_client
        if event.storage_config:
            storage_type = event.storage_config.type
            local_path = event.storage_config.local_path or settings.LOCAL_STORAGE_PATH
            bucket = event.storage_config.bucket or settings.S3_BUCKET

            logger.info(
                "using_event_storage_config",
                document_id=str(document_id),
                storage_type=storage_type,
                local_path=local_path if storage_type == "local" else None,
            )

            # Temporarily set instance storage client for this document
            self.storage_client = get_storage_client(
                storage_type=storage_type,
                bucket=bucket,
                region=settings.AWS_REGION,
                endpoint_url=settings.S3_ENDPOINT_URL,
                access_key=settings.AWS_ACCESS_KEY_ID,
                secret_key=settings.AWS_SECRET_ACCESS_KEY,
                local_path=local_path,
            )

        # Create processing job
        job_id = uuid.uuid4()
        job = ProcessingJobModel(
            job_id=job_id,
            document_id=document_id,
            status=ProcessingStatus.RUNNING.value,
            worker_id=worker_id,
            started_at=datetime.now(timezone.utc),
            metadata={
                "correlation_id": event.correlation_id,
                "s3_key": event.s3_key,
            },
        )
        self.db.add(job)
        await self.db.commit()

        # Update registry state to processing
        await self._update_document_state(document_id, "processing")

        try:
            # Stage 1: Download PDF from S3
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="download")
            stage_start = time.time()
            pdf_content = await self._download_pdf(event.s3_key)
            stage_timings["download"] = time.time() - stage_start

            # Stage 2: PDF Parsing
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="pdf_parsing")
            await self._update_job_stage(job_id, PipelineStage.PDF_PARSING)
            stage_start = time.time()

            # Use parser factory to route to appropriate parser (Docling or GROBID)
            extracted = await self.parser_factory.parse(
                content=pdf_content,
                filename=event.s3_key,  # Use S3 key for file type detection
            )
            stage_timings["pdf_parsing"] = time.time() - stage_start

            # Store extracted text artifact
            extracted_key = await self._store_artifact(
                document_id, "extracted_text.json", extracted.model_dump_json()
            )
            artifacts["extracted_text"] = extracted_key
            await self._mark_stage_complete(job_id, PipelineStage.PDF_PARSING, stage_timings["pdf_parsing"])

            # Stage 3: Section Segmentation
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="section_segmentation")
            await self._update_job_stage(job_id, PipelineStage.SECTION_SEGMENTATION)
            stage_start = time.time()

            sections = self.segmenter.segment(extracted)
            stage_timings["section_segmentation"] = time.time() - stage_start

            # Store structure map artifact
            structure_key = await self._store_artifact(
                document_id,
                "structure_map.json",
                self.segmenter.create_structure_map(sections),
            )
            artifacts["structure_map"] = structure_key
            await self._mark_stage_complete(job_id, PipelineStage.SECTION_SEGMENTATION, stage_timings["section_segmentation"])

            # Stage 4: Chunking
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="chunking")
            await self._update_job_stage(job_id, PipelineStage.CHUNKING)
            stage_start = time.time()

            chunks = self.chunker.chunk_document(document_id, sections)
            stage_timings["chunking"] = time.time() - stage_start

            # Store chunks artifact
            chunks_key = await self._store_artifact(
                document_id,
                "chunks.json",
                [c.model_dump() for c in chunks],
            )
            artifacts["chunks"] = chunks_key
            await self._mark_stage_complete(job_id, PipelineStage.CHUNKING, stage_timings["chunking"])

            # Stage 5: Embedding Generation
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="embedding")
            await self._update_job_stage(job_id, PipelineStage.EMBEDDING)
            stage_start = time.time()

            chunks_with_embeddings = await self.embedding_generator.generate_embeddings(chunks)
            stage_timings["embedding"] = time.time() - stage_start
            await self._mark_stage_complete(job_id, PipelineStage.EMBEDDING, stage_timings["embedding"])

            # Stage 6: Indexing in Qdrant
            logger.info("pipeline_stage_start", document_id=str(document_id), stage="indexing")
            await self._update_job_stage(job_id, PipelineStage.INDEXING)
            stage_start = time.time()

            # Prepare document metadata for Qdrant
            doc_metadata = {
                "doi": event.doi,
                "title": event.title,
            }

            await self.qdrant_client.upsert_chunks(chunks_with_embeddings, doc_metadata)

            # Store chunks in database
            await self._store_chunks(chunks_with_embeddings)
            stage_timings["indexing"] = time.time() - stage_start
            await self._mark_stage_complete(job_id, PipelineStage.INDEXING, stage_timings["indexing"])

            # Stage 7: Knowledge Extraction (entities and relationships)
            entity_count = 0
            if settings.ENABLE_KNOWLEDGE_EXTRACTION:
                logger.info("pipeline_stage_start", document_id=str(document_id), stage="knowledge_extraction")
                await self._update_job_stage(job_id, PipelineStage.KNOWLEDGE_EXTRACTION)
                stage_start = time.time()

                entity_count = await self._extract_knowledge(
                    document_id=document_id,
                    chunks=chunks,
                    doc_metadata=doc_metadata,
                )
                stage_timings["knowledge_extraction"] = time.time() - stage_start
                await self._mark_stage_complete(job_id, PipelineStage.KNOWLEDGE_EXTRACTION, stage_timings["knowledge_extraction"])

                logger.info(
                    "knowledge_extraction_complete",
                    document_id=str(document_id),
                    entity_count=entity_count,
                )

            # Update Document Registry state
            await self._update_document_state(document_id, "indexed")

            # Mark job complete
            total_time = time.time() - start_time
            await self._complete_job(job_id, len(chunks), entity_count, stage_timings)

            # Publish DocumentIndexed event
            await self._publish_indexed_event(
                document_id=document_id,
                chunk_count=len(chunks),
                entity_count=entity_count,
                processing_time=total_time,
                correlation_id=event.correlation_id,
            )

            logger.info(
                "pipeline_complete",
                document_id=str(document_id),
                chunk_count=len(chunks),
                processing_time=total_time,
            )

            return ProcessingResult(
                document_id=document_id,
                success=True,
                chunk_count=len(chunks),
                entity_count=0,
                processing_time_seconds=total_time,
                stage_timings=stage_timings,
                artifacts=artifacts,
            )

        except Exception as e:
            logger.error(
                "pipeline_error",
                document_id=str(document_id),
                error=str(e),
            )

            # Mark job failed
            await self._fail_job(job_id, str(e))

            # Update Document Registry state
            await self._update_document_state(document_id, "failed", error=str(e))

            return ProcessingResult(
                document_id=document_id,
                success=False,
                error=str(e),
                processing_time_seconds=time.time() - start_time,
                stage_timings=stage_timings,
            )

        finally:
            # Restore original storage client if it was changed
            if event.storage_config:
                self.storage_client = original_storage_client

    async def _download_pdf(self, s3_key: str) -> bytes:
        """Download PDF from S3.

        Args:
            s3_key: S3 object key

        Returns:
            PDF content bytes
        """
        return await self.storage_client.download_object(key=s3_key)

    async def _store_artifact(
        self,
        document_id: uuid.UUID,
        filename: str,
        content: str | list | dict,
    ) -> str:
        """Store processing artifact in S3.

        Args:
            document_id: Document ID
            filename: Artifact filename
            content: Content to store

        Returns:
            S3 key
        """
        import json

        if isinstance(content, (list, dict)):
            content = json.dumps(content, default=str)

        s3_key = f"documents/{document_id}/artifacts/{filename}"

        await self.storage_client.upload_bytes(
            bucket=settings.S3_BUCKET,
            key=s3_key,
            data=content.encode("utf-8"),
            content_type="application/json",
        )

        return s3_key

    async def _store_chunks(self, chunks: list[ChunkWithEmbedding]) -> None:
        """Store chunks in database.

        Args:
            chunks: Chunks to store
        """
        for chunk in chunks:
            chunk_model = ChunkModel(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                sequence_number=chunk.sequence_number,
                text=chunk.text,
                section=chunk.section.value if chunk.section else None,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                char_offset_start=chunk.char_offset_start,
                char_offset_end=chunk.char_offset_end,
                token_count=chunk.token_count,
                embedding_id=str(chunk.chunk_id),  # Use chunk_id as Qdrant point ID
                metadata=chunk.metadata,
            )
            self.db.add(chunk_model)

        await self.db.commit()

    async def _extract_knowledge(
        self,
        document_id: uuid.UUID,
        chunks: list[Chunk],
        doc_metadata: dict[str, Any],
    ) -> int:
        """Extract entities and relationships using knowledge extraction service.

        Args:
            document_id: Document ID
            chunks: Document chunks to extract knowledge from
            doc_metadata: Document metadata (title, doi, etc.)

        Returns:
            Number of entities extracted
        """
        total_entities = 0
        total_relationships = 0

        # Call knowledge extraction service for each chunk (batch for efficiency)
        async with httpx.AsyncClient(timeout=120.0) as client:
            # First, create an extraction job
            try:
                job_response = await client.post(
                    f"{settings.KNOWLEDGE_EXTRACTION_URL}/api/v1/extraction/jobs",
                    json={
                        "document_id": str(document_id),
                        "chunk_ids": [str(c.chunk_id) for c in chunks],
                    },
                )
                job_response.raise_for_status()
                job_data = job_response.json()
                logger.info(
                    "knowledge_extraction_job_created",
                    document_id=str(document_id),
                    job_id=job_data.get("job_id"),
                )

                # For immediate extraction, call the extract endpoint for each chunk
                # Process chunks in batches to avoid overwhelming the service
                batch_size = 5
                for i in range(0, len(chunks), batch_size):
                    batch = chunks[i : i + batch_size]
                    tasks = []

                    for chunk in batch:
                        tasks.append(
                            self._extract_chunk_knowledge(
                                client,
                                document_id,
                                chunk,
                                doc_metadata,
                            )
                        )

                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    for result in results:
                        if isinstance(result, Exception):
                            logger.warning(
                                "chunk_extraction_failed",
                                error=str(result),
                            )
                        elif result:
                            total_entities += result.get("entity_count", 0)
                            total_relationships += result.get("relationship_count", 0)

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "knowledge_extraction_service_error",
                    status_code=e.response.status_code,
                    error=str(e),
                )
            except Exception as e:
                logger.warning(
                    "knowledge_extraction_failed",
                    error=str(e),
                )

        logger.info(
            "knowledge_extraction_summary",
            document_id=str(document_id),
            total_entities=total_entities,
            total_relationships=total_relationships,
        )

        return total_entities

    async def _extract_chunk_knowledge(
        self,
        client: httpx.AsyncClient,
        document_id: uuid.UUID,
        chunk: Chunk,
        doc_metadata: dict[str, Any],
    ) -> dict[str, int]:
        """Extract knowledge from a single chunk.

        Args:
            client: HTTP client
            document_id: Document ID
            chunk: Chunk to extract from
            doc_metadata: Document metadata

        Returns:
            Dict with entity_count and relationship_count
        """
        try:
            response = await client.post(
                f"{settings.KNOWLEDGE_EXTRACTION_URL}/api/v1/extraction/extract",
                params={
                    "text": chunk.text,
                    "document_id": str(document_id),
                    "chunk_id": str(chunk.chunk_id),
                },
            )
            response.raise_for_status()
            result = response.json()

            return {
                "entity_count": len(result.get("entities", [])),
                "relationship_count": len(result.get("relationships", [])),
            }

        except Exception as e:
            logger.debug(
                "chunk_extraction_error",
                chunk_id=str(chunk.chunk_id),
                error=str(e),
            )
            return {"entity_count": 0, "relationship_count": 0}

    async def _update_job_stage(self, job_id: uuid.UUID, stage: PipelineStage) -> None:
        """Update job current stage.

        Args:
            job_id: Job ID
            stage: Current stage
        """
        await self.db.execute(
            update(ProcessingJobModel)
            .where(ProcessingJobModel.job_id == job_id)
            .values(current_stage=stage.value)
        )
        await self.db.commit()

    async def _mark_stage_complete(
        self,
        job_id: uuid.UUID,
        stage: PipelineStage,
        timing: float,
    ) -> None:
        """Mark a pipeline stage as complete.

        Args:
            job_id: Job ID
            stage: Completed stage
            timing: Stage timing in seconds
        """
        result = await self.db.execute(
            select(ProcessingJobModel).where(ProcessingJobModel.job_id == job_id)
        )
        job = result.scalar_one_or_none()

        if job:
            stages = list(job.stages_completed or [])
            stages.append(stage.value)

            timings = dict(job.stage_timings or {})
            timings[stage.value] = timing

            await self.db.execute(
                update(ProcessingJobModel)
                .where(ProcessingJobModel.job_id == job_id)
                .values(
                    stages_completed=stages,
                    stage_timings=timings,
                )
            )
            await self.db.commit()

    async def _complete_job(
        self,
        job_id: uuid.UUID,
        chunk_count: int,
        entity_count: int,
        stage_timings: dict[str, float],
    ) -> None:
        """Mark job as complete.

        Args:
            job_id: Job ID
            chunk_count: Number of chunks created
            entity_count: Number of entities extracted
            stage_timings: Stage timing data
        """
        await self.db.execute(
            update(ProcessingJobModel)
            .where(ProcessingJobModel.job_id == job_id)
            .values(
                status=ProcessingStatus.COMPLETED.value,
                current_stage=None,
                completed_at=datetime.now(timezone.utc),
                extra_metadata=ProcessingJobModel.extra_metadata.concat({
                    "chunk_count": chunk_count,
                    "entity_count": entity_count,
                }),
            )
        )
        await self.db.commit()

    async def _fail_job(self, job_id: uuid.UUID, error: str) -> None:
        """Mark job as failed.

        Args:
            job_id: Job ID
            error: Error message
        """
        await self.db.execute(
            update(ProcessingJobModel)
            .where(ProcessingJobModel.job_id == job_id)
            .values(
                status=ProcessingStatus.FAILED.value,
                error_message=error,
                completed_at=datetime.now(timezone.utc),
            )
        )
        await self.db.commit()

    async def _update_document_state(
        self,
        document_id: uuid.UUID,
        state: str,
        error: str | None = None,
    ) -> None:
        """Update document state in registry.

        Args:
            document_id: Document ID
            state: New state
            error: Error message (for failed state)
        """
        registry_url = settings.DOCUMENT_REGISTRY_URL
        if not registry_url:
            logger.warning("registry_url_not_configured")
            return

        payload = {
            "state": state,
            "worker_id": f"processing-{settings.SERVICE_NAME}",
        }
        if error:
            payload["error_message"] = error

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{registry_url}/registry/documents/{document_id}/state",
                    json=payload,
                )
                response.raise_for_status()
        except Exception as e:
            logger.error("registry_state_update_error", error=str(e))

    async def _publish_indexed_event(
        self,
        document_id: uuid.UUID,
        chunk_count: int,
        entity_count: int,
        processing_time: float,
        correlation_id: str,
    ) -> None:
        """Publish DocumentIndexed event.

        Args:
            document_id: Document ID
            chunk_count: Number of chunks
            entity_count: Number of entities
            processing_time: Total processing time
            correlation_id: Correlation ID
        """
        if not self.sqs_client:
            return

        event = DocumentIndexedEvent(
            document_id=document_id,
            chunk_count=chunk_count,
            entity_count=entity_count,
            processing_time_seconds=processing_time,
            correlation_id=correlation_id,
            timestamp=datetime.now(timezone.utc),
        )

        try:
            await self.sqs_client.send_message(
                queue_url=settings.SQS_DOCUMENT_INDEXED_URL,
                message=event.model_dump(),
            )
        except Exception as e:
            logger.error("event_publish_error", error=str(e))

    async def reprocess_document(
        self,
        document_id: uuid.UUID,
        from_stage: PipelineStage | None = None,
    ) -> ProcessingResult:
        """Reprocess a document.

        Args:
            document_id: Document ID to reprocess
            from_stage: Start from specific stage (or beginning)

        Returns:
            Processing result
        """
        # Get document info from registry
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.DOCUMENT_REGISTRY_URL}/registry/documents/{document_id}"
            )
            response.raise_for_status()
            doc_data = response.json()

        # Extract storage config from source_metadata if available
        source_metadata = doc_data.get("source_metadata", {})
        storage_config_data = source_metadata.get("storage_config")
        storage_config = None
        if storage_config_data:
            from services.document_processing.app.core.schemas import StorageConfig
            storage_config = StorageConfig(
                type=storage_config_data.get("type", "s3"),
                local_path=storage_config_data.get("local_path"),
                bucket=storage_config_data.get("bucket"),
            )

        # Create synthetic event for reprocessing
        event = DocumentRegisteredEvent(
            document_id=document_id,
            content_hash=doc_data.get("content_hash", ""),
            doi=doc_data.get("doi"),
            title=doc_data.get("title", ""),
            s3_key=doc_data.get("artifact_pointers", {}).get("pdf", f"documents/{document_id}/original.pdf"),
            user_id=uuid.UUID(doc_data.get("provenance", [{}])[0].get("user_id", str(uuid.uuid4()))),
            correlation_id=f"reprocess-{document_id}",
            timestamp=datetime.now(timezone.utc),
            storage_config=storage_config,
        )

        return await self.process_document(event, f"reprocess-worker-{uuid.uuid4().hex[:8]}")
