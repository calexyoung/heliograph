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
    ) -> str:
        """Send a message to the queue.

        Args:
            message: Message body (Pydantic model or dict)
            message_group_id: Message group ID for FIFO queues
            deduplication_id: Deduplication ID for FIFO queues

        Returns:
            Message ID from SQS
        """
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
                "QueueUrl": self.queue_url,
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
                queue_url=self.queue_url,
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
