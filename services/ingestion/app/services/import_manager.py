"""Import management for external papers."""

import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from services.ingestion.app.config import settings
from services.ingestion.app.core.models import ImportRecordModel, IngestionJobModel
from services.ingestion.app.core.schemas import (
    ImportRecord,
    ImportRequest,
    ImportResponse,
    ImportStatus,
    IngestionJob,
    JobStatus,
    JobType,
    SearchResult,
)
from services.ingestion.app.services.job_manager import JobManager
from services.ingestion.app.services.search import SearchOrchestrator
from services.ingestion.app.upload.handler import UploadHandler
from shared.utils.logging import get_logger
from shared.utils.sqs import SQSClient

logger = get_logger(__name__)


class ImportManager:
    """Manage paper imports from external sources."""

    def __init__(
        self,
        db: AsyncSession,
        search_orchestrator: SearchOrchestrator | None = None,
        upload_handler: UploadHandler | None = None,
        sqs_client: SQSClient | None = None,
    ):
        """Initialize import manager.

        Args:
            db: Database session
            search_orchestrator: Search service
            upload_handler: PDF upload handler
            sqs_client: SQS client for events
        """
        self.db = db
        self.job_manager = JobManager(db)
        self.search = search_orchestrator or SearchOrchestrator()
        self.upload_handler = upload_handler or UploadHandler()
        self.sqs_client = sqs_client

    async def close(self) -> None:
        """Close resources."""
        await self.search.close()

    async def import_paper(self, request: ImportRequest) -> ImportResponse:
        """Import a paper from external source.

        Args:
            request: Import request

        Returns:
            Import response with job ID
        """
        # Determine source from identifiers
        if request.arxiv_id:
            source = "arxiv"
        elif request.doi:
            source = "crossref"
        elif request.bibcode:
            source = "scixplorer"
        elif request.url:
            source = "url"
        else:
            source = "unknown"

        # Create import job
        job = await self.job_manager.create_job(
            job_type=JobType.IMPORT,
            source=source,
            metadata={
                "doi": request.doi,
                "arxiv_id": request.arxiv_id,
                "bibcode": request.bibcode,
                "url": request.url,
                "download_pdf": request.download_pdf,
            },
        )

        # Process import asynchronously
        # In production, this would be handled by a worker
        # For now, we process inline
        job_id_str = str(job.job_id)
        try:
            result = await self._process_import(job_id_str, request)
            return result
        except Exception as e:
            logger.error("import_error", job_id=job_id_str, error=str(e))
            await self.job_manager.update_status(
                job_id_str,
                JobStatus.FAILED,
                error=str(e),
            )
            return ImportResponse(
                job_id=job_id_str,
                status=ImportStatus.FAILED,
                error=str(e),
            )

    async def _process_import(
        self,
        job_id: str,
        request: ImportRequest,
    ) -> ImportResponse:
        """Process an import request.

        Args:
            job_id: Job identifier
            request: Import request

        Returns:
            Import response
        """
        await self.job_manager.update_status(job_id, JobStatus.RUNNING)

        # Fetch paper metadata
        paper = await self._fetch_paper_metadata(request)

        if not paper:
            await self.job_manager.update_status(
                job_id,
                JobStatus.FAILED,
                error="Paper not found in any source",
            )
            return ImportResponse(
                job_id=job_id,
                status=ImportStatus.NOT_FOUND,
                error="Paper not found",
            )

        # Check for existing import
        existing = await self._check_existing_import(paper)
        if existing:
            doc_id_str = str(existing.document_id) if existing.document_id else None
            await self.job_manager.update_status(
                job_id,
                JobStatus.COMPLETED,
                result_count=1,
                metadata_updates={"duplicate_of": doc_id_str},
            )
            return ImportResponse(
                job_id=job_id,
                status=ImportStatus.DUPLICATE,
                document_id=doc_id_str,
                paper=paper,
            )

        # Generate document ID
        document_id = str(uuid.uuid4())

        # Download PDF if requested and available
        pdf_result = None
        if request.download_pdf and paper.pdf_url:
            pdf_result = await self.upload_handler.upload_from_url(
                url=paper.pdf_url,
                document_id=document_id,
            )

        # Create import record
        record = await self._create_import_record(
            document_id=document_id,
            paper=paper,
            pdf_result=pdf_result,
        )

        # Register with Document Registry
        registry_result = await self._register_document(document_id, paper, pdf_result)

        if not registry_result["success"]:
            await self.job_manager.update_status(
                job_id,
                JobStatus.FAILED,
                error=registry_result.get("error", "Registration failed"),
            )
            return ImportResponse(
                job_id=job_id,
                status=ImportStatus.FAILED,
                error=registry_result.get("error"),
            )

        # Update job status
        await self.job_manager.update_status(
            job_id,
            JobStatus.COMPLETED,
            result_count=1,
            metadata_updates={
                "document_id": document_id,
                "pdf_downloaded": pdf_result is not None and pdf_result.get("success"),
            },
        )

        # Publish event
        if self.sqs_client:
            await self._publish_import_event(document_id, paper)

        logger.info(
            "paper_imported",
            job_id=job_id,
            document_id=document_id,
            doi=paper.doi,
            source=paper.source,
        )

        return ImportResponse(
            job_id=job_id,
            status=ImportStatus.IMPORTED,
            document_id=document_id,
            paper=paper,
        )

    async def _fetch_paper_metadata(
        self,
        request: ImportRequest,
    ) -> SearchResult | None:
        """Fetch paper metadata from external sources.

        Args:
            request: Import request with identifiers

        Returns:
            Paper metadata or None
        """
        # Try DOI first
        if request.doi:
            paper = await self.search.get_paper_by_doi(request.doi)
            if paper:
                return paper

        # Try arXiv ID
        if request.arxiv_id:
            paper = await self.search.get_paper_by_arxiv(request.arxiv_id)
            if paper:
                return paper

        # Try bibcode (ADS)
        if request.bibcode:
            paper = await self.search.connectors["scixplorer"].get_paper(request.bibcode)
            if paper:
                return paper

        # Try direct URL fetch
        if request.url:
            # For now, we can't extract metadata from arbitrary URLs
            # This would require PDF parsing
            pass

        return None

    async def _check_existing_import(
        self,
        paper: SearchResult,
    ) -> ImportRecord | None:
        """Check if paper already imported.

        Args:
            paper: Paper metadata

        Returns:
            Existing import record or None
        """
        # Check by DOI
        if paper.doi:
            result = await self.db.execute(
                select(ImportRecordModel).where(
                    ImportRecordModel.doi == paper.doi.lower()
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                return self._record_to_schema(existing)

        # Check by external ID
        if paper.external_id:
            result = await self.db.execute(
                select(ImportRecordModel).where(
                    ImportRecordModel.external_id == paper.external_id,
                    ImportRecordModel.source == paper.source,
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                return self._record_to_schema(existing)

        return None

    async def _create_import_record(
        self,
        document_id: str,
        paper: SearchResult,
        pdf_result: dict | None,
    ) -> ImportRecord:
        """Create import record in database.

        Args:
            document_id: Generated document ID
            paper: Paper metadata
            pdf_result: PDF upload result

        Returns:
            Created import record
        """
        record = ImportRecordModel(
            document_id=document_id,
            user_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),  # Default user for now
            source=paper.source,
            external_id=paper.external_id,
            doi=paper.doi.lower() if paper.doi else None,
            title=paper.title,
            authors=[a.model_dump() for a in paper.authors],
            year=paper.year,
            journal=paper.journal,
            abstract=paper.abstract,
            pdf_url=paper.pdf_url,
            s3_key=pdf_result.get("s3_key") if pdf_result and pdf_result.get("success") else None,
            content_hash=pdf_result.get("content_hash") if pdf_result and pdf_result.get("success") else None,
            source_metadata=paper.source_metadata,
            status=ImportStatus.IMPORTED.value,
            created_at=datetime.now(timezone.utc),
        )

        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)

        return self._record_to_schema(record)

    async def _register_document(
        self,
        document_id: str,
        paper: SearchResult,
        pdf_result: dict | None,
    ) -> dict:
        """Register document with Document Registry service.

        Args:
            document_id: Document ID
            paper: Paper metadata
            pdf_result: PDF upload result

        Returns:
            Registration result
        """
        registry_url = settings.document_registry_url

        if not registry_url:
            logger.warning("registry_url_not_configured")
            return {"success": True, "message": "Registry not configured"}

        # Use system user for automated imports
        system_user_id = "00000000-0000-0000-0000-000000000000"

        payload = {
            "doi": paper.doi,
            "title": paper.title,
            "authors": [a.model_dump() for a in paper.authors],
            "year": paper.year,
            "journal": paper.journal,
            "source": paper.source,
            "source_metadata": paper.source_metadata or {},
            "user_id": system_user_id,
        }

        if pdf_result and pdf_result.get("success"):
            payload["content_hash"] = pdf_result["content_hash"]
            payload["s3_key"] = pdf_result["s3_key"]

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{registry_url}/registry/documents",
                    json=payload,
                )
                response.raise_for_status()

                return {
                    "success": True,
                    "data": response.json(),
                }

        except Exception as e:
            logger.error("registry_error", error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

    async def _publish_import_event(
        self,
        document_id: str,
        paper: SearchResult,
    ) -> None:
        """Publish document imported event.

        Args:
            document_id: Document ID
            paper: Paper metadata
        """
        if not self.sqs_client:
            return

        event = {
            "event_type": "DocumentImported",
            "document_id": document_id,
            "doi": paper.doi,
            "source": paper.source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        try:
            await self.sqs_client.send_message(
                queue_url=settings.sqs_document_events_url,
                message=event,
            )
        except Exception as e:
            logger.error("event_publish_error", error=str(e))

    async def get_import_record(self, document_id: str) -> ImportRecord | None:
        """Get import record by document ID.

        Args:
            document_id: Document identifier

        Returns:
            Import record or None
        """
        result = await self.db.execute(
            select(ImportRecordModel).where(
                ImportRecordModel.document_id == document_id
            )
        )
        record = result.scalar_one_or_none()

        if not record:
            return None

        return self._record_to_schema(record)

    async def list_imports(
        self,
        source: str | None = None,
        status: ImportStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ImportRecord]:
        """List import records.

        Args:
            source: Filter by source
            status: Filter by status
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of import records
        """
        query = select(ImportRecordModel)

        if source:
            query = query.where(ImportRecordModel.source == source)

        if status:
            query = query.where(ImportRecordModel.status == status.value)

        query = query.order_by(ImportRecordModel.created_at.desc())
        query = query.offset(offset).limit(limit)

        result = await self.db.execute(query)
        records = result.scalars().all()

        return [self._record_to_schema(r) for r in records]

    async def batch_import(
        self,
        papers: list[SearchResult],
        download_pdf: bool = True,
    ) -> list[ImportResponse]:
        """Import multiple papers.

        Args:
            papers: List of papers to import
            download_pdf: Whether to download PDFs

        Returns:
            List of import responses
        """
        responses = []

        for paper in papers:
            request = ImportRequest(
                source=paper.source,
                doi=paper.doi,
                arxiv_id=paper.source_metadata.get("arxiv_id") if paper.source_metadata else None,
                download_pdf=download_pdf,
            )

            response = await self.import_paper(request)
            responses.append(response)

        return responses

    def _record_to_schema(self, model: ImportRecordModel) -> ImportRecord:
        """Convert model to schema.

        Args:
            model: Database model

        Returns:
            Pydantic schema
        """
        return ImportRecord(
            document_id=model.document_id,
            source=model.source,
            external_id=model.external_id,
            doi=model.doi,
            title=model.title,
            authors=model.authors,
            year=model.year,
            journal=model.journal,
            abstract=model.abstract,
            pdf_url=model.pdf_url,
            s3_key=model.s3_key,
            content_hash=model.content_hash,
            source_metadata=model.source_metadata,
            status=ImportStatus(model.status),
            created_at=model.created_at,
            updated_at=model.updated_at,
        )
