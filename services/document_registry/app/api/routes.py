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
    ErrorResponse,
    HealthResponse,
    PaginatedDocumentList,
    ReadinessResponse,
    StateTransitionRequest,
    StateTransitionResponse,
    UpdateDocumentRequest,
)
from shared.utils.logging import get_correlation_id
import base64
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


def create_error_response(
    error_code: str,
    message: str,
    details: dict | None = None,
) -> dict:
    """Create a standardized error response dict.

    Args:
        error_code: Machine-readable error code (e.g., "DOCUMENT_NOT_FOUND")
        message: Human-readable error message
        details: Optional additional error details

    Returns:
        Dict suitable for HTTPException detail parameter
    """
    response = ErrorResponse(
        error_code=error_code,
        message=message,
        details=details,
        correlation_id=get_correlation_id(),
    )
    return response.model_dump(exclude_none=True)


@router.get("/health", response_model=HealthResponse)
async def health_check(settings: AppSettings) -> HealthResponse:
    """Health check endpoint.

    Returns basic liveness status. This endpoint should always return
    quickly and only fail if the service is completely unresponsive.
    """
    try:
        # Verify settings are loaded correctly
        _ = settings.service_name
        return HealthResponse(
            status="healthy",
            service="document-registry",
            version="0.1.0",
        )
    except Exception:
        return HealthResponse(
            status="unhealthy",
            service="document-registry",
            version="0.1.0",
        )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check(
    db: DBSession,
    sqs: SQS,
    settings: AppSettings,
) -> ReadinessResponse:
    """Readiness check endpoint.

    Verifies all dependencies are available and the service is ready
    to handle requests. Returns detailed status for each dependency.
    """
    checks = {}

    # Check database connection
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        logger.warning("readiness_check_database_failed", error=str(e))
        checks["database"] = False

    # Check SQS connectivity (only in non-test environments)
    if settings.environment != "test":
        try:
            # Verify SQS client is configured
            checks["sqs"] = sqs is not None and sqs.queue_url is not None
        except Exception as e:
            logger.warning("readiness_check_sqs_failed", error=str(e))
            checks["sqs"] = False
    else:
        checks["sqs"] = True  # Skip SQS check in test environment

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


@router.get("/documents/paginated", response_model=PaginatedDocumentList)
async def list_documents_paginated(
    db: DBSession,
    status: DocumentStatus | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> PaginatedDocumentList:
    """List documents with cursor-based pagination.

    Provides stable pagination using document_id as cursor.
    More reliable than offset-based pagination for concurrent modifications.

    Args:
        status: Filter by document status
        limit: Maximum documents to return (default 100, max 1000)
        cursor: Base64-encoded document_id from previous page's next_cursor

    Returns:
        Paginated list with items, total count, and next cursor
    """
    from uuid import UUID

    with REQUEST_LATENCY.labels(endpoint="list_documents_paginated").time():
        repository = DocumentRepository(db)

        # Decode cursor if provided
        cursor_uuid: UUID | None = None
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
                cursor_uuid = UUID(decoded)
            except (ValueError, TypeError) as e:
                from fastapi import status as http_status
                raise HTTPException(
                    status_code=http_status.HTTP_400_BAD_REQUEST,
                    detail=create_error_response(
                        error_code="INVALID_CURSOR",
                        message="Invalid pagination cursor",
                        details={"cursor": cursor, "error": str(e)},
                    ),
                )

        # Cap limit at 1000
        effective_limit = min(limit, 1000)

        # Fetch one extra to determine if there are more pages
        documents = await repository.list_documents_cursor(
            status=status,
            limit=effective_limit + 1,
            cursor=cursor_uuid,
        )

        # Get total count for metadata
        total = await repository.count_documents(status=status)

        # Determine if there are more pages
        has_more = len(documents) > effective_limit
        if has_more:
            documents = documents[:effective_limit]

        # Generate next cursor from last document
        next_cursor: str | None = None
        if has_more and documents:
            last_doc_id = str(documents[-1].document_id)
            next_cursor = base64.urlsafe_b64encode(last_doc_id.encode()).decode()

        items = [
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

        return PaginatedDocumentList(
            items=items,
            total=total,
            limit=effective_limit,
            next_cursor=next_cursor,
            has_more=has_more,
        )


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

        # Capture document_id early to avoid accessing expired object after rollback
        document_id = document.document_id
        document_id_str = str(document_id)

        # Handle race condition where document was created by concurrent request
        if not created:
            DEDUP_HITS.labels(match_type="race_condition").inc()
            REGISTRATION_REQUESTS.labels(status="duplicate").inc()
            logger.info(
                "document_registration_race_condition",
                existing_document_id=document_id_str,
            )
            return DocumentRegistrationResponse(
                document_id=document_id,
                status="duplicate",
                existing_document_id=document_id,
            )

        # Add provenance
        await repository.add_provenance(
            document_id=document_id,
            source=request.source,
            user_id=request.user_id,
            metadata_snapshot=request.source_metadata or {},
            upload_id=request.upload_id,
            connector_job_id=request.connector_job_id,
        )

        # Use provided S3 key or derive from upload_id/connector_job_id
        if request.s3_key:
            s3_key = request.s3_key
        elif request.upload_id:
            s3_key = f"uploads/{request.upload_id}/document.pdf"
        elif request.connector_job_id:
            s3_key = f"imports/{request.connector_job_id}/{document_id_str}.pdf"
        else:
            s3_key = f"documents/{document_id_str}/document.pdf"

        # Publish event BEFORE committing to ensure consistency
        # If event publishing fails, we rollback the transaction
        message_id = await event_publisher.publish_document_registered(
            document=document,
            s3_key=s3_key,
            user_id=request.user_id,
            storage_config=request.storage_config,
        )

        if message_id is None:
            # Event publishing failed - log warning but continue with registration
            # Documents should still be registered even if event system is unavailable
            EVENT_PUBLISH_FAILURES.labels(event_type="document_registered").inc()
            logger.warning(
                "document_registered_event_publish_failed",
                document_id=document_id_str,
            )

        # Commit the transaction
        await db.commit()

        REGISTRATION_REQUESTS.labels(status="queued").inc()
        logger.info(
            "document_registered",
            document_id=document_id_str,
            event_message_id=message_id,
        )

        return DocumentRegistrationResponse(
            document_id=document_id,
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
                detail=create_error_response(
                    error_code="DOCUMENT_NOT_FOUND",
                    message="Document not found",
                    details={"document_id": str(document_id)},
                ),
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
            source_metadata=document.source_metadata,
            provenance=provenance,
            created_at=document.created_at,
            updated_at=document.updated_at,
            last_processed_at=document.last_processed_at,
        )


@router.patch("/documents/{document_id}")
async def update_document(
    document_id: UUID,
    request: UpdateDocumentRequest,
    db: DBSession,
) -> dict:
    """Update document attributes.

    Currently supports updating artifact_pointers.
    """
    repository = DocumentRepository(db)
    document = await repository.get_by_id(document_id)

    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=create_error_response(
                error_code="DOCUMENT_NOT_FOUND",
                message="Document not found",
                details={"document_id": str(document_id)},
            ),
        )

    if request.artifact_pointers is not None:
        # Merge with existing artifact_pointers
        # Use dict() to create a copy so SQLAlchemy detects the change
        existing = dict(document.artifact_pointers or {})
        existing.update(request.artifact_pointers)
        await repository.update_artifact_pointers(document_id, existing)
        await db.commit()

    return {"status": "updated", "document_id": str(document_id)}


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: UUID,
    db: DBSession,
    permanent: bool = False,
) -> dict:
    """Delete a document (soft delete by default).

    Args:
        document_id: Document UUID to delete
        permanent: If True, permanently delete. If False, soft delete (default).

    Returns:
        Status indicating success
    """
    with REQUEST_LATENCY.labels(endpoint="delete_document").time():
        repository = DocumentRepository(db)

        if permanent:
            # Hard delete - remove from database entirely
            document = await repository.get_by_id(document_id)
            if document is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=create_error_response(
                        error_code="DOCUMENT_NOT_FOUND",
                        message="Document not found",
                        details={"document_id": str(document_id)},
                    ),
                )
            await db.delete(document)
            await db.commit()
            logger.info(
                "document_hard_deleted",
                document_id=str(document_id),
            )
            return {"status": "deleted", "document_id": str(document_id), "permanent": True}

        # Soft delete
        document, success = await repository.soft_delete(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=create_error_response(
                    error_code="DOCUMENT_NOT_FOUND",
                    message="Document not found",
                    details={"document_id": str(document_id)},
                ),
            )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=create_error_response(
                    error_code="ALREADY_DELETED",
                    message="Document is already deleted",
                    details={"document_id": str(document_id)},
                ),
            )

        await db.commit()
        logger.info(
            "document_soft_deleted",
            document_id=str(document_id),
        )
        return {"status": "deleted", "document_id": str(document_id), "permanent": False}


@router.post("/documents/{document_id}/restore")
async def restore_document(
    document_id: UUID,
    db: DBSession,
) -> dict:
    """Restore a soft-deleted document.

    Args:
        document_id: Document UUID to restore

    Returns:
        Status indicating success
    """
    with REQUEST_LATENCY.labels(endpoint="restore_document").time():
        repository = DocumentRepository(db)

        document, success = await repository.restore(document_id)
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=create_error_response(
                    error_code="DOCUMENT_NOT_FOUND",
                    message="Document not found",
                    details={"document_id": str(document_id)},
                ),
            )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=create_error_response(
                    error_code="NOT_DELETED",
                    message="Document is not deleted",
                    details={"document_id": str(document_id)},
                ),
            )

        await db.commit()
        logger.info(
            "document_restored",
            document_id=str(document_id),
        )
        return {"status": "restored", "document_id": str(document_id)}


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
                detail=create_error_response(
                    error_code="DOCUMENT_NOT_FOUND",
                    message="Document not found",
                    details={"document_id": str(document_id)},
                ),
            )

        previous_state = document.status

        # Validate transition
        try:
            StateMachine.validate_transition(document.status, request.state)
        except InvalidTransitionError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=create_error_response(
                    error_code="INVALID_STATE_TRANSITION",
                    message=str(e),
                    details={
                        "current_state": document.status.value,
                        "target_state": request.state.value,
                    },
                ),
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
                detail=create_error_response(
                    error_code="STATE_CONFLICT",
                    message="Document state has changed since last read",
                    details={
                        "current_state": updated_doc.status.value if updated_doc else None,
                        "expected_state": request.expected_state.value if request.expected_state else None,
                    },
                ),
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
