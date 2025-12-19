"""Rate limiting middleware using Redis."""

import time
from typing import Callable

from fastapi import HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

from services.api_gateway.app.config import get_settings
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Token bucket rate limiter using Redis."""

    def __init__(
        self,
        redis_client,
        requests_per_minute: int = 60,
        burst: int = 10,
    ):
        """Initialize rate limiter.

        Args:
            redis_client: Redis client instance
            requests_per_minute: Sustained request rate
            burst: Maximum burst size
        """
        self.redis = redis_client
        self.rate = requests_per_minute / 60.0  # Tokens per second
        self.burst = burst

    async def is_allowed(
        self,
        key: str,
        cost: int = 1,
    ) -> tuple[bool, dict]:
        """Check if request is allowed under rate limit.

        Uses token bucket algorithm stored in Redis.

        Args:
            key: Rate limit key (e.g., user_id or IP)
            cost: Number of tokens to consume

        Returns:
            Tuple of (allowed, metadata with remaining/reset info)
        """
        now = time.time()
        bucket_key = f"ratelimit:{key}"

        # Lua script for atomic token bucket operation
        lua_script = """
        local key = KEYS[1]
        local rate = tonumber(ARGV[1])
        local burst = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])
        local cost = tonumber(ARGV[4])

        local bucket = redis.call('HMGET', key, 'tokens', 'last_update')
        local tokens = tonumber(bucket[1]) or burst
        local last_update = tonumber(bucket[2]) or now

        -- Add tokens based on time passed
        local elapsed = now - last_update
        tokens = math.min(burst, tokens + elapsed * rate)

        -- Check if we can consume
        local allowed = 0
        if tokens >= cost then
            tokens = tokens - cost
            allowed = 1
        end

        -- Update bucket
        redis.call('HMSET', key, 'tokens', tokens, 'last_update', now)
        redis.call('EXPIRE', key, 120)  -- Expire after 2 minutes of inactivity

        -- Calculate reset time (when bucket will be full)
        local reset = now + (burst - tokens) / rate

        return {allowed, tokens, reset}
        """

        try:
            result = await self.redis.eval(
                lua_script,
                1,
                bucket_key,
                self.rate,
                self.burst,
                now,
                cost,
            )

            allowed = bool(result[0])
            remaining = max(0, int(result[1]))
            reset_at = int(result[2])

            return allowed, {
                "limit": self.burst,
                "remaining": remaining,
                "reset": reset_at,
            }

        except Exception as e:
            logger.error("rate_limit_error", error=str(e))
            # Fail open if Redis is unavailable
            return True, {"limit": self.burst, "remaining": self.burst, "reset": 0}

    def get_key(self, request: Request) -> str:
        """Get rate limit key for request.

        Uses user_id if authenticated, otherwise client IP.

        Args:
            request: FastAPI request

        Returns:
            Rate limit key string
        """
        # Check for authenticated user
        if hasattr(request.state, "user") and request.state.user:
            return f"user:{request.state.user.user_id}"

        # Check for API key
        if hasattr(request.state, "api_key") and request.state.api_key:
            return f"apikey:{request.state.api_key.key_id}"

        # Fall back to IP address
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware to apply rate limiting to requests."""

    def __init__(
        self,
        app,
        redis_client,
        requests_per_minute: int = 60,
        burst: int = 10,
        exclude_paths: list[str] | None = None,
    ):
        """Initialize middleware.

        Args:
            app: ASGI application
            redis_client: Redis client
            requests_per_minute: Default rate limit
            burst: Default burst size
            exclude_paths: Paths to exclude from rate limiting
        """
        super().__init__(app)
        self.limiter = RateLimiter(redis_client, requests_per_minute, burst)
        self.exclude_paths = exclude_paths or ["/health", "/ready", "/metrics"]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with rate limiting.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response
        """
        # Skip excluded paths
        if any(request.url.path.startswith(p) for p in self.exclude_paths):
            return await call_next(request)

        # Get rate limit key
        key = self.limiter.get_key(request)

        # Check rate limit
        allowed, metadata = await self.limiter.is_allowed(key)

        if not allowed:
            logger.warning(
                "rate_limit_exceeded",
                key=key,
                path=request.url.path,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={
                    "X-RateLimit-Limit": str(metadata["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(metadata["reset"]),
                    "Retry-After": str(max(1, metadata["reset"] - int(time.time()))),
                },
            )

        # Process request
        response = await call_next(request)

        # Add rate limit headers
        response.headers["X-RateLimit-Limit"] = str(metadata["limit"])
        response.headers["X-RateLimit-Remaining"] = str(metadata["remaining"])
        response.headers["X-RateLimit-Reset"] = str(metadata["reset"])

        return response
