"""Redis session management."""

import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from services.api_gateway.app.config import get_settings
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class SessionManager:
    """Manages user sessions in Redis."""

    SESSION_PREFIX = "session:"
    USER_SESSIONS_PREFIX = "user_sessions:"

    def __init__(self, redis_client):
        """Initialize session manager.

        Args:
            redis_client: Redis client instance
        """
        self.redis = redis_client
        self.settings = get_settings()
        self.ttl = self.settings.session_ttl_seconds

    async def create_session(
        self,
        user_id: UUID,
        session_id: str,
        data: dict[str, Any] | None = None,
    ) -> bool:
        """Create a new session.

        Args:
            user_id: User UUID
            session_id: Unique session identifier
            data: Additional session data

        Returns:
            True if session was created
        """
        session_key = f"{self.SESSION_PREFIX}{session_id}"
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"

        session_data = {
            "user_id": str(user_id),
            "session_id": session_id,
            "created_at": datetime.utcnow().isoformat(),
            "last_activity": datetime.utcnow().isoformat(),
            **(data or {}),
        }

        try:
            # Store session data
            await self.redis.setex(
                session_key,
                self.ttl,
                json.dumps(session_data),
            )

            # Add to user's session set
            await self.redis.sadd(user_sessions_key, session_id)
            await self.redis.expire(user_sessions_key, self.ttl * 2)

            logger.debug(
                "session_created",
                user_id=str(user_id),
                session_id=session_id,
            )
            return True

        except Exception as e:
            logger.error("session_create_error", error=str(e))
            return False

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get session data.

        Args:
            session_id: Session identifier

        Returns:
            Session data or None if not found
        """
        session_key = f"{self.SESSION_PREFIX}{session_id}"

        try:
            data = await self.redis.get(session_key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error("session_get_error", error=str(e))
            return None

    async def update_session(
        self,
        session_id: str,
        data: dict[str, Any],
    ) -> bool:
        """Update session data.

        Args:
            session_id: Session identifier
            data: Data to merge into session

        Returns:
            True if session was updated
        """
        session_key = f"{self.SESSION_PREFIX}{session_id}"

        try:
            existing = await self.get_session(session_id)
            if not existing:
                return False

            # Merge data
            existing.update(data)
            existing["last_activity"] = datetime.utcnow().isoformat()

            # Update with refreshed TTL
            await self.redis.setex(
                session_key,
                self.ttl,
                json.dumps(existing),
            )

            return True

        except Exception as e:
            logger.error("session_update_error", error=str(e))
            return False

    async def touch_session(self, session_id: str) -> bool:
        """Refresh session TTL (extend expiration).

        Args:
            session_id: Session identifier

        Returns:
            True if session was refreshed
        """
        session_key = f"{self.SESSION_PREFIX}{session_id}"

        try:
            # Get and update last_activity
            existing = await self.get_session(session_id)
            if not existing:
                return False

            existing["last_activity"] = datetime.utcnow().isoformat()

            await self.redis.setex(
                session_key,
                self.ttl,
                json.dumps(existing),
            )
            return True

        except Exception as e:
            logger.error("session_touch_error", error=str(e))
            return False

    async def delete_session(self, session_id: str) -> bool:
        """Delete a session.

        Args:
            session_id: Session identifier

        Returns:
            True if session was deleted
        """
        session_key = f"{self.SESSION_PREFIX}{session_id}"

        try:
            # Get user_id to remove from user's session set
            session = await self.get_session(session_id)
            if session:
                user_id = session.get("user_id")
                if user_id:
                    user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"
                    await self.redis.srem(user_sessions_key, session_id)

            await self.redis.delete(session_key)

            logger.debug("session_deleted", session_id=session_id)
            return True

        except Exception as e:
            logger.error("session_delete_error", error=str(e))
            return False

    async def delete_user_sessions(self, user_id: UUID) -> int:
        """Delete all sessions for a user.

        Args:
            user_id: User UUID

        Returns:
            Number of sessions deleted
        """
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"

        try:
            session_ids = await self.redis.smembers(user_sessions_key)
            count = 0

            for session_id in session_ids:
                session_key = f"{self.SESSION_PREFIX}{session_id}"
                await self.redis.delete(session_key)
                count += 1

            await self.redis.delete(user_sessions_key)

            logger.info(
                "user_sessions_deleted",
                user_id=str(user_id),
                count=count,
            )
            return count

        except Exception as e:
            logger.error("user_sessions_delete_error", error=str(e))
            return 0

    async def get_user_session_count(self, user_id: UUID) -> int:
        """Get number of active sessions for a user.

        Args:
            user_id: User UUID

        Returns:
            Number of active sessions
        """
        user_sessions_key = f"{self.USER_SESSIONS_PREFIX}{user_id}"

        try:
            return await self.redis.scard(user_sessions_key)
        except Exception as e:
            logger.error("session_count_error", error=str(e))
            return 0
