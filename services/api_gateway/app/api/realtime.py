"""Real-time update routes (WebSocket and SSE)."""

from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from services.api_gateway.app.auth.jwt import verify_token
from services.api_gateway.app.realtime.pubsub import PubSubManager
from services.api_gateway.app.realtime.websocket import WebSocketManager
from services.api_gateway.app.realtime.sse import SSEManager
from shared.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Real-time"])

# Note: In production, these would be initialized with actual Redis clients
# For now, we'll use dependency injection patterns


def get_pubsub() -> PubSubManager:
    """Get pub/sub manager dependency."""
    # This would be injected from app state in production
    raise NotImplementedError("Redis client not configured")


def get_ws_manager(pubsub: PubSubManager = Depends(get_pubsub)) -> WebSocketManager:
    """Get WebSocket manager dependency."""
    return WebSocketManager(pubsub)


def get_sse_manager(pubsub: PubSubManager = Depends(get_pubsub)) -> SSEManager:
    """Get SSE manager dependency."""
    return SSEManager(pubsub)


@router.websocket("/ws/jobs/{job_id}")
async def websocket_job_updates(
    websocket: WebSocket,
    job_id: str,
) -> None:
    """WebSocket endpoint for real-time job updates.

    Connect to receive real-time updates for a specific job.
    Authentication is done via query parameter or first message.

    Messages:
    - Server sends: {"type": "job_update", "data": {...}}
    - Server sends: {"type": "heartbeat", "data": {"job_id": "..."}}
    - Client can send: {"type": "ping"} -> receives {"type": "pong"}
    - Client can send: {"type": "get_status"} -> receives current status

    The connection will close automatically when the job completes.
    """
    # Extract token from query params for WebSocket auth
    token = websocket.query_params.get("token")
    user_id = None

    if token:
        token_data = verify_token(token)
        if token_data:
            user_id = UUID(token_data.sub)

    # Note: In production, require authentication
    # For now, allow unauthenticated for development

    try:
        # Get managers from app state (would be set in main.py)
        pubsub = websocket.app.state.pubsub
        ws_manager = WebSocketManager(pubsub)

        await ws_manager.connect(
            websocket=websocket,
            job_id=job_id,
            user_id=user_id,
        )

    except WebSocketDisconnect:
        logger.debug("websocket_client_disconnected", job_id=job_id)

    except AttributeError:
        # App state not configured - reject connection
        await websocket.close(code=1013, reason="Service unavailable")


@router.get("/events/jobs/{job_id}")
async def sse_job_updates(
    job_id: str,
) -> EventSourceResponse:
    """SSE endpoint for real-time job updates.

    Alternative to WebSocket for clients that don't support WebSocket.
    Returns Server-Sent Events stream.

    Events:
    - event: job_update, data: {...job update JSON...}
    - event: complete, data: {...final status...}
    - event: error, data: {...error info...}

    Example client usage:
    ```javascript
    const events = new EventSource('/api/events/jobs/123');
    events.addEventListener('job_update', (e) => {
        console.log(JSON.parse(e.data));
    });
    events.addEventListener('complete', (e) => {
        events.close();
    });
    ```
    """
    # Note: In production, this would need auth via cookie or query param

    from fastapi import Request
    from starlette.requests import Request as StarletteRequest

    # Get SSE manager from app state
    # For now, return a placeholder response
    async def placeholder_events():
        yield {
            "event": "error",
            "data": '{"error": "SSE not configured"}',
        }

    return EventSourceResponse(placeholder_events())
