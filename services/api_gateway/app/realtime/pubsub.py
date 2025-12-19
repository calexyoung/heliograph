"""Redis pub/sub for real-time job updates."""

import asyncio
import json
from datetime import datetime
from typing import Any, AsyncIterator, Callable
from uuid import UUID

from pydantic import BaseModel

from shared.utils.logging import get_logger

logger = get_logger(__name__)


class JobUpdate(BaseModel):
    """Job status update message."""

    job_id: str
    status: str
    progress: float = 0.0  # 0-100
    message: str | None = None
    data: dict[str, Any] | None = None
    timestamp: datetime = datetime.utcnow()


class PubSubManager:
    """Manages Redis pub/sub for job updates."""

    CHANNEL_PREFIX = "job_updates:"

    def __init__(self, redis_client):
        """Initialize pub/sub manager.

        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self._subscriptions: dict[str, asyncio.Task] = {}

    def _channel_name(self, job_id: str) -> str:
        """Get Redis channel name for a job."""
        return f"{self.CHANNEL_PREFIX}{job_id}"

    async def publish_update(self, update: JobUpdate) -> int:
        """Publish a job update.

        Args:
            update: Job update to publish

        Returns:
            Number of subscribers that received the message
        """
        channel = self._channel_name(update.job_id)
        message = update.model_dump_json()

        try:
            count = await self.redis.publish(channel, message)
            logger.debug(
                "job_update_published",
                job_id=update.job_id,
                status=update.status,
                subscribers=count,
            )
            return count
        except Exception as e:
            logger.error("publish_error", job_id=update.job_id, error=str(e))
            return 0

    async def subscribe(self, job_id: str) -> AsyncIterator[JobUpdate]:
        """Subscribe to updates for a job.

        Args:
            job_id: Job ID to subscribe to

        Yields:
            Job updates as they arrive
        """
        channel = self._channel_name(job_id)
        pubsub = self.redis.pubsub()

        try:
            await pubsub.subscribe(channel)
            logger.debug("subscribed_to_job", job_id=job_id)

            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        yield JobUpdate(**data)
                    except (json.JSONDecodeError, ValueError) as e:
                        logger.warning(
                            "invalid_update_message",
                            job_id=job_id,
                            error=str(e),
                        )

        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            logger.debug("unsubscribed_from_job", job_id=job_id)

    async def subscribe_with_timeout(
        self,
        job_id: str,
        timeout: float = 300.0,  # 5 minutes default
    ) -> AsyncIterator[JobUpdate]:
        """Subscribe to updates with timeout.

        Args:
            job_id: Job ID to subscribe to
            timeout: Timeout in seconds

        Yields:
            Job updates as they arrive
        """
        channel = self._channel_name(job_id)
        pubsub = self.redis.pubsub()

        try:
            await pubsub.subscribe(channel)

            start_time = asyncio.get_event_loop().time()

            async for message in pubsub.listen():
                # Check timeout
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > timeout:
                    logger.debug("subscription_timeout", job_id=job_id)
                    break

                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        update = JobUpdate(**data)
                        yield update

                        # Stop if job completed or failed
                        if update.status in ("completed", "failed", "cancelled"):
                            break

                    except (json.JSONDecodeError, ValueError):
                        continue

        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def get_last_update(self, job_id: str) -> JobUpdate | None:
        """Get the last update for a job from cache.

        Args:
            job_id: Job ID

        Returns:
            Last update or None
        """
        key = f"job_last_update:{job_id}"

        try:
            data = await self.redis.get(key)
            if data:
                return JobUpdate(**json.loads(data))
            return None
        except Exception:
            return None

    async def cache_update(self, update: JobUpdate, ttl: int = 3600) -> None:
        """Cache the last update for a job.

        Args:
            update: Update to cache
            ttl: Cache TTL in seconds
        """
        key = f"job_last_update:{update.job_id}"

        try:
            await self.redis.setex(key, ttl, update.model_dump_json())
        except Exception as e:
            logger.warning("cache_update_error", job_id=update.job_id, error=str(e))
