"""SQS publisher/consumer helpers."""

import json
from typing import Any

from aiobotocore.session import get_session
from pydantic import BaseModel

from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SQSClient:
    """Async SQS client wrapper."""

    def __init__(
        self,
        queue_url: str,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
    ):
        """Initialize SQS client.

        Args:
            queue_url: SQS queue URL
            region: AWS region
            endpoint_url: Custom endpoint (for LocalStack/ElasticMQ)
        """
        self.queue_url = queue_url
        self.region = region
        self.endpoint_url = endpoint_url
        self._session = get_session()

    async def send_message(
        self,
        message: BaseModel | dict[str, Any],
        message_group_id: str | None = None,
        deduplication_id: str | None = None,
        queue_url: str | None = None,
    ) -> str:
        """Send a message to the queue.

        Args:
            message: Message body (Pydantic model or dict)
            message_group_id: Message group ID for FIFO queues
            deduplication_id: Deduplication ID for FIFO queues
            queue_url: Optional queue URL (defaults to client's queue_url)

        Returns:
            Message ID from SQS
        """
        url = queue_url or self.queue_url
        if isinstance(message, BaseModel):
            body = message.model_dump_json()
        else:
            body = json.dumps(message)

        async with self._session.create_client(
            "sqs",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            kwargs: dict[str, Any] = {
                "QueueUrl": url,
                "MessageBody": body,
            }

            if message_group_id:
                kwargs["MessageGroupId"] = message_group_id
            if deduplication_id:
                kwargs["MessageDeduplicationId"] = deduplication_id

            response = await client.send_message(**kwargs)
            message_id = response["MessageId"]

            logger.info(
                "sqs_message_sent",
                message_id=message_id,
                queue_url=url,
            )

            return message_id

    async def send_message_batch(
        self,
        messages: list[BaseModel | dict[str, Any]],
    ) -> list[str]:
        """Send multiple messages in a batch.

        Args:
            messages: List of message bodies

        Returns:
            List of message IDs
        """
        entries = []
        for i, message in enumerate(messages):
            if isinstance(message, BaseModel):
                body = message.model_dump_json()
            else:
                body = json.dumps(message)
            entries.append({"Id": str(i), "MessageBody": body})

        async with self._session.create_client(
            "sqs",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            response = await client.send_message_batch(
                QueueUrl=self.queue_url,
                Entries=entries,
            )

            successful = response.get("Successful", [])
            failed = response.get("Failed", [])

            if failed:
                logger.error(
                    "sqs_batch_partial_failure",
                    failed_count=len(failed),
                    queue_url=self.queue_url,
                )

            return [msg["MessageId"] for msg in successful]

    async def receive_messages(
        self,
        queue_url: str | None = None,
        max_messages: int = 10,
        visibility_timeout: int = 30,
        wait_time: int = 20,
    ) -> list[dict[str, Any]]:
        """Receive messages from the queue.

        Args:
            queue_url: Queue URL (uses default if not specified)
            max_messages: Maximum messages to receive (1-10)
            visibility_timeout: Visibility timeout in seconds
            wait_time: Long polling wait time in seconds

        Returns:
            List of messages
        """
        url = queue_url or self.queue_url

        async with self._session.create_client(
            "sqs",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            response = await client.receive_message(
                QueueUrl=url,
                MaxNumberOfMessages=min(max_messages, 10),
                VisibilityTimeout=visibility_timeout,
                WaitTimeSeconds=wait_time,
                AttributeNames=["All"],
                MessageAttributeNames=["All"],
            )

            messages = response.get("Messages", [])
            if messages:
                logger.info(
                    "sqs_messages_received",
                    count=len(messages),
                    queue_url=url,
                )
            return messages

    async def delete_message(
        self,
        receipt_handle: str,
        queue_url: str | None = None,
    ) -> None:
        """Delete a message from the queue.

        Args:
            receipt_handle: Message receipt handle
            queue_url: Queue URL (uses default if not specified)
        """
        url = queue_url or self.queue_url

        async with self._session.create_client(
            "sqs",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            await client.delete_message(
                QueueUrl=url,
                ReceiptHandle=receipt_handle,
            )
            logger.info(
                "sqs_message_deleted",
                queue_url=url,
            )

    async def change_visibility(
        self,
        receipt_handle: str,
        visibility_timeout: int,
        queue_url: str | None = None,
    ) -> None:
        """Change message visibility timeout.

        Args:
            receipt_handle: Message receipt handle
            visibility_timeout: New visibility timeout in seconds
            queue_url: Queue URL (uses default if not specified)
        """
        url = queue_url or self.queue_url

        async with self._session.create_client(
            "sqs",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
        ) as client:
            await client.change_message_visibility(
                QueueUrl=url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=visibility_timeout,
            )
            logger.info(
                "sqs_visibility_changed",
                queue_url=url,
                new_timeout=visibility_timeout,
            )
