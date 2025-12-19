"""WebSocket connection manager for real-time updates."""

import asyncio
import json
from typing import Any
from uuid import UUID

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.api_gateway.app.config import get_settings
from services.api_gateway.app.realtime.pubsub import PubSubManager, JobUpdate
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class WebSocketMessage(BaseModel):
    """WebSocket message format."""

    type: str
    data: dict[str, Any] | None = None


class WebSocketManager:
    """Manages WebSocket connections for job updates."""

    def __init__(self, pubsub: PubSubManager):
        """Initialize WebSocket manager.

        Args:
            pubsub: Redis pub/sub manager
        """
        self.pubsub = pubsub
        self.settings = get_settings()
        self._active_connections: dict[str, set[WebSocket]] = {}

    async def connect(
        self,
        websocket: WebSocket,
        job_id: str,
        user_id: UUID | None = None,
    ) -> None:
        """Handle new WebSocket connection.

        Args:
            websocket: WebSocket connection
            job_id: Job ID to subscribe to
            user_id: User ID for authorization
        """
        await websocket.accept()

        # Add to active connections
        if job_id not in self._active_connections:
            self._active_connections[job_id] = set()
        self._active_connections[job_id].add(websocket)

        logger.info(
            "websocket_connected",
            job_id=job_id,
            user_id=str(user_id) if user_id else None,
        )

        try:
            # Send current status if available
            last_update = await self.pubsub.get_last_update(job_id)
            if last_update:
                await self._send_update(websocket, last_update)

            # Start heartbeat and subscription tasks
            heartbeat_task = asyncio.create_task(
                self._heartbeat(websocket, job_id)
            )
            subscription_task = asyncio.create_task(
                self._handle_subscription(websocket, job_id)
            )
            receive_task = asyncio.create_task(
                self._handle_messages(websocket, job_id)
            )

            # Wait for any task to complete (disconnect, error, etc.)
            done, pending = await asyncio.wait(
                [heartbeat_task, subscription_task, receive_task],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # Cancel remaining tasks
            for task in pending:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        except WebSocketDisconnect:
            logger.debug("websocket_disconnected", job_id=job_id)

        except Exception as e:
            logger.error("websocket_error", job_id=job_id, error=str(e))

        finally:
            # Remove from active connections
            if job_id in self._active_connections:
                self._active_connections[job_id].discard(websocket)
                if not self._active_connections[job_id]:
                    del self._active_connections[job_id]

    async def _heartbeat(self, websocket: WebSocket, job_id: str) -> None:
        """Send periodic heartbeat messages.

        Args:
            websocket: WebSocket connection
            job_id: Job ID
        """
        interval = self.settings.ws_heartbeat_interval

        while True:
            await asyncio.sleep(interval)
            try:
                await websocket.send_json({
                    "type": "heartbeat",
                    "data": {"job_id": job_id},
                })
            except Exception:
                break

    async def _handle_subscription(
        self,
        websocket: WebSocket,
        job_id: str,
    ) -> None:
        """Handle Redis subscription and forward updates.

        Args:
            websocket: WebSocket connection
            job_id: Job ID to subscribe to
        """
        async for update in self.pubsub.subscribe_with_timeout(job_id):
            try:
                await self._send_update(websocket, update)

                # Close connection if job is done
                if update.status in ("completed", "failed", "cancelled"):
                    await websocket.close(code=1000)
                    break

            except Exception:
                break

    async def _handle_messages(
        self,
        websocket: WebSocket,
        job_id: str,
    ) -> None:
        """Handle incoming WebSocket messages.

        Args:
            websocket: WebSocket connection
            job_id: Job ID
        """
        while True:
            try:
                message = await websocket.receive_json()

                # Handle ping/pong
                if message.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})

                # Handle status request
                elif message.get("type") == "get_status":
                    last_update = await self.pubsub.get_last_update(job_id)
                    if last_update:
                        await self._send_update(websocket, last_update)

            except WebSocketDisconnect:
                raise
            except Exception as e:
                logger.warning("ws_message_error", error=str(e))

    async def _send_update(
        self,
        websocket: WebSocket,
        update: JobUpdate,
    ) -> None:
        """Send job update to WebSocket.

        Args:
            websocket: WebSocket connection
            update: Job update to send
        """
        await websocket.send_json({
            "type": "job_update",
            "data": update.model_dump(mode="json"),
        })

    async def broadcast_to_job(self, job_id: str, update: JobUpdate) -> int:
        """Broadcast update to all connections for a job.

        Args:
            job_id: Job ID
            update: Update to broadcast

        Returns:
            Number of connections that received the update
        """
        connections = self._active_connections.get(job_id, set())
        sent_count = 0

        for websocket in connections.copy():
            try:
                await self._send_update(websocket, update)
                sent_count += 1
            except Exception:
                # Remove dead connections
                connections.discard(websocket)

        return sent_count

    def get_connection_count(self, job_id: str | None = None) -> int:
        """Get number of active connections.

        Args:
            job_id: Optional job ID to filter by

        Returns:
            Number of connections
        """
        if job_id:
            return len(self._active_connections.get(job_id, set()))
        return sum(len(conns) for conns in self._active_connections.values())
