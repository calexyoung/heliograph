"""Pipeline worker for consuming SQS messages."""

import asyncio
import json
import signal
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from services.document_processing.app.config import settings
from services.document_processing.app.core.schemas import DocumentRegisteredEvent
from services.document_processing.app.pipeline.orchestrator import PipelineOrchestrator
from shared.utils.logging import get_logger
from shared.utils.sqs import SQSClient

logger = get_logger(__name__)


class PipelineWorker:
    """Worker that consumes DocumentRegistered events and processes documents."""

    def __init__(
        self,
        worker_id: str | None = None,
        max_concurrent: int = 5,
    ):
        """Initialize pipeline worker.

        Args:
            worker_id: Unique worker identifier
            max_concurrent: Maximum concurrent document processing
        """
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.max_concurrent = max_concurrent
        self.running = False
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: set[asyncio.Task] = set()

        # Database engine
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            pool_size=max_concurrent + 2,
        )
        self.async_session = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        # SQS client
        self.sqs_client = SQSClient(
            endpoint_url=settings.SQS_ENDPOINT_URL,
            region=settings.AWS_REGION,
            access_key=settings.AWS_ACCESS_KEY_ID,
            secret_key=settings.AWS_SECRET_ACCESS_KEY,
        )

    async def start(self) -> None:
        """Start the worker."""
        logger.info("worker_starting", worker_id=self.worker_id)
        self.running = True

        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Start polling loop
        await self._poll_loop()

    async def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("worker_stopping", worker_id=self.worker_id)
        self.running = False

        # Wait for in-flight tasks
        if self._tasks:
            logger.info("waiting_for_tasks", count=len(self._tasks))
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close database connections
        await self.engine.dispose()

        logger.info("worker_stopped", worker_id=self.worker_id)

    async def _poll_loop(self) -> None:
        """Main polling loop for SQS messages."""
        while self.running:
            try:
                # Receive messages from SQS
                messages = await self.sqs_client.receive_messages(
                    queue_url=settings.SQS_DOCUMENT_REGISTERED_URL,
                    max_messages=min(self.max_concurrent, 10),
                    visibility_timeout=settings.PIPELINE_VISIBILITY_TIMEOUT,
                    wait_time=20,  # Long polling
                )

                if not messages:
                    continue

                # Process messages concurrently
                for message in messages:
                    task = asyncio.create_task(
                        self._process_message(message)
                    )
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("poll_error", error=str(e))
                await asyncio.sleep(5)  # Back off on errors

    async def _process_message(self, message: dict[str, Any]) -> None:
        """Process a single SQS message.

        Args:
            message: SQS message
        """
        receipt_handle = message.get("ReceiptHandle")
        message_id = message.get("MessageId")

        async with self.semaphore:
            try:
                # Parse message body
                body = json.loads(message.get("Body", "{}"))
                event = DocumentRegisteredEvent(**body)

                logger.info(
                    "processing_document",
                    worker_id=self.worker_id,
                    document_id=str(event.document_id),
                    message_id=message_id,
                )

                # Process document
                async with self.async_session() as session:
                    orchestrator = PipelineOrchestrator(
                        db=session,
                        sqs_client=self.sqs_client,
                    )
                    result = await orchestrator.process_document(event, self.worker_id)

                if result.success:
                    # Delete message on success
                    await self.sqs_client.delete_message(
                        queue_url=settings.SQS_DOCUMENT_REGISTERED_URL,
                        receipt_handle=receipt_handle,
                    )
                    logger.info(
                        "document_processed",
                        document_id=str(event.document_id),
                        chunk_count=result.chunk_count,
                    )
                else:
                    # Handle failure
                    await self._handle_failure(message, result.error)

            except json.JSONDecodeError as e:
                logger.error("message_parse_error", error=str(e), message_id=message_id)
                # Move to DLQ
                await self._move_to_dlq(message, f"Parse error: {e}")

            except Exception as e:
                logger.error(
                    "processing_error",
                    error=str(e),
                    message_id=message_id,
                )
                await self._handle_failure(message, str(e))

    async def _handle_failure(self, message: dict[str, Any], error: str) -> None:
        """Handle processing failure.

        Args:
            message: Original SQS message
            error: Error message
        """
        receipt_handle = message.get("ReceiptHandle")
        attributes = message.get("Attributes", {})
        receive_count = int(attributes.get("ApproximateReceiveCount", "0"))

        if receive_count >= settings.PIPELINE_MAX_RETRIES:
            # Move to DLQ after max retries
            logger.warning(
                "max_retries_exceeded",
                message_id=message.get("MessageId"),
                receive_count=receive_count,
            )
            await self._move_to_dlq(message, error)
        else:
            # Change visibility timeout for retry with backoff
            delay = min(
                settings.PIPELINE_RETRY_DELAY * (2 ** (receive_count - 1)),
                600  # Max 10 minutes
            )
            logger.info(
                "scheduling_retry",
                message_id=message.get("MessageId"),
                retry_count=receive_count,
                delay_seconds=delay,
            )
            await self.sqs_client.change_visibility(
                queue_url=settings.SQS_DOCUMENT_REGISTERED_URL,
                receipt_handle=receipt_handle,
                visibility_timeout=delay,
            )

    async def _move_to_dlq(self, message: dict[str, Any], error: str) -> None:
        """Move message to dead-letter queue.

        Args:
            message: Original SQS message
            error: Error message
        """
        if not settings.SQS_DLQ_URL:
            logger.warning("dlq_not_configured")
            return

        try:
            # Send to DLQ with error metadata
            dlq_message = {
                "original_body": message.get("Body"),
                "original_message_id": message.get("MessageId"),
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "worker_id": self.worker_id,
            }

            await self.sqs_client.send_message(
                queue_url=settings.SQS_DLQ_URL,
                message=dlq_message,
            )

            # Delete from main queue
            await self.sqs_client.delete_message(
                queue_url=settings.SQS_DOCUMENT_REGISTERED_URL,
                receipt_handle=message.get("ReceiptHandle"),
            )

            logger.info(
                "moved_to_dlq",
                message_id=message.get("MessageId"),
            )

        except Exception as e:
            logger.error("dlq_move_error", error=str(e))


async def run_worker():
    """Run the pipeline worker."""
    worker = PipelineWorker(
        max_concurrent=5,
    )
    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
