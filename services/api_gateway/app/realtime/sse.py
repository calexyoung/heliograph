"""Server-Sent Events (SSE) for real-time updates."""

import asyncio
from typing import AsyncIterator

from sse_starlette.sse import EventSourceResponse

from services.api_gateway.app.config import get_settings
from services.api_gateway.app.realtime.pubsub import PubSubManager, JobUpdate
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SSEManager:
    """Manages SSE connections for job updates."""

    def __init__(self, pubsub: PubSubManager):
        """Initialize SSE manager.

        Args:
            pubsub: Redis pub/sub manager
        """
        self.pubsub = pubsub
        self.settings = get_settings()

    async def job_updates(
        self,
        job_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[dict]:
        """Generate SSE events for job updates.

        Args:
            job_id: Job ID to subscribe to
            timeout: Timeout in seconds

        Yields:
            SSE event data
        """
        # Send initial status if available
        last_update = await self.pubsub.get_last_update(job_id)
        if last_update:
            yield {
                "event": "job_update",
                "data": last_update.model_dump_json(),
                "retry": self.settings.sse_retry_timeout,
            }

            # If job already complete, send complete event and stop
            if last_update.status in ("completed", "failed", "cancelled"):
                yield {
                    "event": "complete",
                    "data": last_update.model_dump_json(),
                }
                return

        # Subscribe to updates
        try:
            async for update in self.pubsub.subscribe_with_timeout(job_id, timeout):
                yield {
                    "event": "job_update",
                    "data": update.model_dump_json(),
                    "retry": self.settings.sse_retry_timeout,
                }

                # Send complete event and stop if job is done
                if update.status in ("completed", "failed", "cancelled"):
                    yield {
                        "event": "complete",
                        "data": update.model_dump_json(),
                    }
                    return

        except asyncio.CancelledError:
            logger.debug("sse_subscription_cancelled", job_id=job_id)
            return

        except Exception as e:
            logger.error("sse_error", job_id=job_id, error=str(e))
            yield {
                "event": "error",
                "data": f'{{"error": "{str(e)}"}}',
            }

    async def create_response(
        self,
        job_id: str,
        timeout: float = 300.0,
    ) -> EventSourceResponse:
        """Create an SSE response for job updates.

        Args:
            job_id: Job ID to subscribe to
            timeout: Timeout in seconds

        Returns:
            EventSourceResponse for streaming
        """
        logger.info("sse_connection_started", job_id=job_id)

        return EventSourceResponse(
            self.job_updates(job_id, timeout),
            ping=self.settings.ws_heartbeat_interval,
        )
