"""API routes for Document Registry service."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from prometheus_client import Counter, Histogram
from sqlalchemy import text

from services.document_registry.app.api.schemas import (
    DocumentDetailResponse,
    DocumentListItem,
    DocumentRegistrationRequest,
    DocumentRegistrationResponse,
    HealthResponse,
    ReadinessResponse,
    StateTransitionRequest,
    StateTransitionResponse,
)
from services.document_registry.app.core.dedup import DeduplicationService
from services.document_registry.app.core.normalizers import normalize_doi, normalize_title
from services.document_registry.app.core.state_machine import InvalidTransitionError, StateMachine
from services.document_registry.app.db.repository import DocumentRepository
from services.document_registry.app.dependencies import (
    AppSettings,
    DBSession,
    SQS,
)
from services.document_registry.app.events.publisher import DocumentEventPublisher
from shared.schemas.document import DocumentStatus, ProvenanceEntry
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Metrics
REGISTRATION_REQUESTS = Counter(
    "registry_registration_requests_total",
    "Total registration requests",
    ["status"],
)
DEDUP_HITS = Counter(
    "registry_dedup_hits_total",
    "Total deduplication hits",
    ["match_type"],
)
STATE_TRANSITIONS = Counter(
    "registry_state_transitions_total",
    "Total state transitions",
    ["from_state", "to_state"],
)
CONFLICTS = Counter(
    "registry_conflicts_total",
    "Total optimistic locking conflicts",
)
REQUEST_LATENCY = Histogram(
    "registry_request_duration_seconds",
    "Request latency in seconds",
    ["endpoint"],
)
EVENT_PUBLISH_FAILURES = Counter(
    "registry_event_publish_failures_total",
    "Total event publishing failures",
    ["event_type"],
)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy", service="document-registry")


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(db: DBSession) -> ReadinessResponse:
    """Readiness check endpoint."""
    checks = {}

    # Check database connection
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        checks["database"] = False

    ready = all(checks.values())
    return ReadinessResponse(ready=ready, checks=checks)


@router.get("/documents", response_model=list[DocumentListItem])
async def list_documents(
    db: DBSession,
    status: DocumentStatus | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DocumentListItem]:
    """List documents with optional filtering.

    Args:
        status: Filter by document status
        limit: Maximum documents to return (default 100)
        offset: Number of documents to skip (default 0)

    Returns:
        List of documents
    """
    with REQUEST_LATENCY.labels(endpoint="list_documents").time():
        repository = DocumentRepository(db)
        documents = await repository.list_documents(
            status=status,
            limit=min(limit, 1000),  # Cap at 1000
            offset=offset,
        )

        return [
            DocumentListItem(
                document_id=doc.document_id,
                doi=doc.doi,
                content_hash=doc.content_hash,
                title=doc.title,
                authors=doc.authors,
                journal=doc.journal,
                year=doc.year,
                status=doc.status,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
            for doc in documents
        ]


@router.post("/documents", response_model=DocumentRegistrationResponse)
async def register_document(
    request: DocumentRegistrationRequest,
    db: DBSession,
    sqs: SQS,
    settings: AppSettings,
) -> DocumentRegistrationResponse:
    """Register a new document.

    Performs deduplication and either:
    - Returns existing document ID if duplicate
    - Creates new document and publishes event if new
    """
    with REQUEST_LATENCY.labels(endpoint="register_document").time():
        repository = DocumentRepository(db)
        dedup_service = DeduplicationService(db, settings.fuzzy_match_threshold)
        event_publisher = DocumentEventPublisher(sqs)

        # Check for duplicates
        result = await dedup_service.check_duplicate(
            doi=request.doi,
            content_hash=request.content_hash,
            title=request.title,
            year=request.year,
        )

        if result.is_duplicate:
            # Handle duplicate
            DEDUP_HITS.labels(match_type=result.match_type.value).inc()
            REGISTRATION_REQUESTS.labels(status="duplicate").inc()

            existing = result.existing_document
            await dedup_service.handle_duplicate(
                existing_document=existing,
                new_source_metadata=request.source_metadata or {},
                source=request.source,
                user_id=request.user_id,
                upload_id=request.upload_id,
                connector_job_id=request.connector_job_id,
            )

            # Always publish duplicate event for all match types
            # Use content_hash if available, otherwise use DOI as identifier
            request_identifier = (
                request.content_hash or
                existing.content_hash or
                f"doi:{request.doi or existing.doi}"
            )
            message_id = await event_publisher.publish_duplicate_detected(
                content_hash=request_identifier,
                existing_document_id=existing.document_id,
                match_type=result.match_type.value,
                user_id=request.user_id,
            )
            if message_id is None:
                EVENT_PUBLISH_FAILURES.labels(event_type="duplicate_detected").inc()
                logger.warning(
                    "duplicate_event_publish_failed",
                    document_id=str(existing.document_id),
                    match_type=result.match_type.value,
                )

            logger.info(
                "document_registration_duplicate",
                existing_document_id=str(existing.document_id),
                match_type=result.match_type.value,
            )

            return DocumentRegistrationResponse(
                document_id=existing.document_id,
                status="duplicate",
                existing_document_id=existing.document_id,
            )

        # Create new document (using INSERT ON CONFLICT for race safety)
        normalized_title = normalize_title(request.title)
        normalized_doi = normalize_doi(request.doi)

        document, created = await repository.create(
            doi=normalized_doi,
            content_hash=request.content_hash,
            title=request.title,
            title_normalized=normalized_title,
            authors=[author.model_dump() for author in request.authors],
            subtitle=request.subtitle,
            journal=request.journal,
            year=request.year,
            source_metadata=request.source_metadata,
        )

        # Handle race condition where document was created by concurrent request
        if not created:
            DEDUP_HITS.labels(match_type="race_condition").inc()
            REGISTRATION_REQUESTS.labels(status="duplicate").inc()
            logger.info(
                "document_registration_race_condition",
                existing_document_id=str(document.document_id),
            )
            return DocumentRegistrationResponse(
                document_id=document.document_id,
                status="duplicate",
                existing_document_id=document.document_id,
            )

        # Add provenance
        await repository.add_provenance(
            document_id=document.document_id,
            source=request.source,
            user_id=request.user_id,
            metadata_snapshot=request.source_metadata or {},
            upload_id=request.upload_id,
            connector_job_id=request.connector_job_id,
        )

        # Derive S3 key from upload_id or connector_job_id
        # Validate that we have a valid UUID for S3 key construction
        if request.upload_id:
            s3_key = f"uploads/{request.upload_id}/document.pdf"
        elif request.connector_job_id:
            s3_key = f"imports/{request.connector_job_id}/{document.document_id}.pdf"
        else:
            s3_key = f"documents/{document.document_id}/document.pdf"

        # Publish event BEFORE committing to ensure consistency
        # If event publishing fails, we rollback the transaction
        message_id = await event_publisher.publish_document_registered(
            document=document,
            s3_key=s3_key,
            user_id=request.user_id,
        )

        if message_id is None:
            # Event publishing failed - rollback and return error
            EVENT_PUBLISH_FAILURES.labels(event_type="document_registered").inc()
            await db.rollback()
            logger.error(
                "document_registered_event_publish_failed",
                document_id=str(document.document_id),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error_code": "EVENT_PUBLISH_FAILED",
                    "message": "Failed to publish document registration event. Please retry.",
                },
            )

        # Event published successfully, now commit the transaction
        await db.commit()

        REGISTRATION_REQUESTS.labels(status="queued").inc()
        logger.info(
            "document_registered",
            document_id=str(document.document_id),
            event_message_id=message_id,
        )

        return DocumentRegistrationResponse(
            document_id=document.document_id,
            status="queued",
        )


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_document(
    document_id: UUID,
    db: DBSession,
) -> DocumentDetailResponse:
    """Get document details by ID."""
    with REQUEST_LATENCY.labels(endpoint="get_document").time():
        repository = DocumentRepository(db)
        document = await repository.get_by_id(document_id, include_provenance=True)

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
            )

        # Convert provenance records to response format
        provenance = [
            ProvenanceEntry(
                provenance_id=p.provenance_id,
                source=p.source,
                source_query=p.source_query,
                source_identifier=p.source_identifier,
                connector_job_id=p.connector_job_id,
                upload_id=p.upload_id,
                user_id=p.user_id,
                metadata_snapshot=p.metadata_snapshot,
                created_at=p.created_at,
            )
            for p in document.provenance_records
        ]

        return DocumentDetailResponse(
            document_id=document.document_id,
            doi=document.doi,
            content_hash=document.content_hash,
            title=document.title,
            authors=document.authors,
            journal=document.journal,
            year=document.year,
            status=document.status,
            error_message=document.error_message,
            artifact_pointers=document.artifact_pointers,
            provenance=provenance,
            created_at=document.created_at,
            updated_at=document.updated_at,
            last_processed_at=document.last_processed_at,
        )


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: UUID,
    db: DBSession,
    artifact_pointers: dict | None = None,
) -> dict:
    """Update document attributes.

    Currently supports updating artifact_pointers.
    """
    repository = DocumentRepository(db)
    document = await repository.get_by_id(document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
        )

    if artifact_pointers is not None:
        # Merge with existing artifact_pointers
        existing = document.artifact_pointers or {}
        existing.update(artifact_pointers)
        await repository.update_artifact_pointers(document_id, existing)
        await db.commit()

    return {"status": "updated", "document_id": str(document_id)}


@router.post("/documents/{document_id}/state", response_model=StateTransitionResponse)
async def transition_state(
    document_id: UUID,
    request: StateTransitionRequest,
    db: DBSession,
    sqs: SQS,
) -> StateTransitionResponse:
    """Transition document state."""
    with REQUEST_LATENCY.labels(endpoint="transition_state").time():
        repository = DocumentRepository(db)
        event_publisher = DocumentEventPublisher(sqs)

        document = await repository.get_by_id(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error_code": "DOCUMENT_NOT_FOUND", "message": "Document not found"},
            )

        previous_state = document.status

        # Validate transition
        try:
            StateMachine.validate_transition(document.status, request.state)
        except InvalidTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error_code": "INVALID_STATE_TRANSITION",
                    "message": str(e),
                    "current_state": document.status.value,
                    "target_state": request.state.value,
                },
            )

        # Attempt transition with optimistic locking
        updated_doc, success = await repository.update_status(
            document_id=document_id,
            new_status=request.state,
            worker_id=request.worker_id,
            error_message=request.error_message,
            artifact_pointers=request.artifact_pointers,
            expected_status=request.expected_state,
        )

        if not success:
            CONFLICTS.inc()
            # Publish failure event
            await event_publisher.publish_state_transition_failed(
                document_id=document_id,
                from_state=previous_state.value,
                to_state=request.state.value,
                error_message="Optimistic lock conflict: expected state does not match",
                worker_id=request.worker_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "STATE_CONFLICT",
                    "message": "Document state has changed since last read",
                    "current_state": updated_doc.status.value if updated_doc else None,
                    "expected_state": request.expected_state.value if request.expected_state else None,
                },
            )

        await db.commit()

        STATE_TRANSITIONS.labels(
            from_state=previous_state.value,
            to_state=request.state.value,
        ).inc()

        logger.info(
            "state_transition",
            document_id=str(document_id),
            from_state=previous_state.value,
            to_state=request.state.value,
            worker_id=request.worker_id,
        )

        return StateTransitionResponse(
            document_id=document_id,
            previous_state=previous_state,
            new_state=request.state,
            success=True,
        )
