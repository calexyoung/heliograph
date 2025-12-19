"""SQS event publisher for document events."""

from datetime import datetime, timezone
from uuid import UUID

from prometheus_client import Counter


def utc_now() -> datetime:
    """Return current UTC time with timezone info."""
    return datetime.now(timezone.utc)

from services.document_registry.app.db.models import DocumentModel
from shared.schemas.events import (
    DocumentDuplicateEvent,
    DocumentRegisteredEvent,
    StateTransitionFailedEvent,
    StorageConfig,
)
from shared.utils.logging import get_correlation_id, get_logger
from shared.utils.sqs import SQSClient

logger = get_logger(__name__)

# Metrics
EVENTS_PUBLISHED = Counter(
    "registry_events_published_total",
    "Total events published",
    ["event_type"],
)
EVENTS_FAILED = Counter(
    "registry_events_failed_total",
    "Total events that failed to publish",
    ["event_type"],
)


class DocumentEventPublisher:
    """Publisher for document-related SQS events."""

    def __init__(self, sqs_client: SQSClient):
        """Initialize publisher with SQS client.

        Args:
            sqs_client: Configured SQS client
        """
        self.sqs_client = sqs_client

    async def publish_document_registered(
        self,
        document: DocumentModel,
        s3_key: str,
        user_id: UUID,
        storage_config: dict | None = None,
    ) -> str | None:
        """Publish DocumentRegistered event.

        Args:
            document: Registered document model
            s3_key: S3 key where PDF is stored
            user_id: User who registered the document
            storage_config: Optional storage configuration (type, local_path, bucket)

        Returns:
            Message ID if successful, None if failed
        """
        # Convert storage config dict to StorageConfig model if provided
        storage = None
        if storage_config:
            storage = StorageConfig(
                type=storage_config.get("type", "s3"),
                local_path=storage_config.get("local_path"),
                bucket=storage_config.get("bucket"),
            )

        event = DocumentRegisteredEvent(
            document_id=document.document_id,
            content_hash=document.content_hash,
            doi=document.doi,
            title=document.title,
            s3_key=s3_key,
            user_id=user_id,
            storage_config=storage,
            correlation_id=get_correlation_id(),
            timestamp=utc_now(),
        )

        try:
            message_id = await self.sqs_client.send_message(event)
            EVENTS_PUBLISHED.labels(event_type="DocumentRegistered").inc()
            logger.info(
                "event_published",
                event_type="DocumentRegistered",
                document_id=str(document.document_id),
                message_id=message_id,
            )
            return message_id
        except Exception as e:
            EVENTS_FAILED.labels(event_type="DocumentRegistered").inc()
            logger.error(
                "event_publish_failed",
                event_type="DocumentRegistered",
                document_id=str(document.document_id),
                error=str(e),
            )
            return None

    async def publish_duplicate_detected(
        self,
        content_hash: str,
        existing_document_id: UUID,
        match_type: str,
        user_id: UUID,
    ) -> str | None:
        """Publish DocumentDuplicate event.

        Args:
            content_hash: Content hash of the attempted registration
            existing_document_id: ID of the existing document
            match_type: Type of duplicate match found
            user_id: User who attempted registration

        Returns:
            Message ID if successful, None if failed
        """
        event = DocumentDuplicateEvent(
            new_document_request_hash=content_hash,
            existing_document_id=existing_document_id,
            match_type=match_type,
            user_id=user_id,
            correlation_id=get_correlation_id(),
            timestamp=utc_now(),
        )

        try:
            message_id = await self.sqs_client.send_message(event)
            EVENTS_PUBLISHED.labels(event_type="DocumentDuplicate").inc()
            logger.info(
                "event_published",
                event_type="DocumentDuplicate",
                existing_document_id=str(existing_document_id),
                message_id=message_id,
            )
            return message_id
        except Exception as e:
            EVENTS_FAILED.labels(event_type="DocumentDuplicate").inc()
            logger.error(
                "event_publish_failed",
                event_type="DocumentDuplicate",
                error=str(e),
            )
            return None

    async def publish_state_transition_failed(
        self,
        document_id: UUID,
        from_state: str,
        to_state: str,
        error_message: str,
        worker_id: str,
    ) -> str | None:
        """Publish StateTransitionFailed event.

        Args:
            document_id: Document ID
            from_state: Previous state
            to_state: Attempted new state
            error_message: Error description
            worker_id: Worker that attempted the transition

        Returns:
            Message ID if successful, None if failed
        """
        event = StateTransitionFailedEvent(
            document_id=document_id,
            from_state=from_state,
            to_state=to_state,
            error_message=error_message,
            worker_id=worker_id,
            correlation_id=get_correlation_id(),
            timestamp=utc_now(),
        )

        try:
            message_id = await self.sqs_client.send_message(event)
            EVENTS_PUBLISHED.labels(event_type="StateTransitionFailed").inc()
            logger.info(
                "event_published",
                event_type="StateTransitionFailed",
                document_id=str(document_id),
                message_id=message_id,
            )
            return message_id
        except Exception as e:
            EVENTS_FAILED.labels(event_type="StateTransitionFailed").inc()
            logger.error(
                "event_publish_failed",
                event_type="StateTransitionFailed",
                error=str(e),
            )
            return None
