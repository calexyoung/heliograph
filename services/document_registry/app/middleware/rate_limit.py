"""Rate limiting middleware for Document Registry service."""

import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from services.document_registry.app.api.schemas import ErrorResponse
from shared.utils.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


class TokenBucket:
    """Token bucket rate limiter implementation."""

    def __init__(self, rate: float, burst: int):
        """Initialize token bucket.

        Args:
            rate: Tokens per second to add
            burst: Maximum tokens (bucket capacity)
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self.lock = Lock()

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens from the bucket.

        Args:
            tokens: Number of tokens to consume

        Returns:
            True if tokens were consumed, False if rate limited
        """
        with self.lock:
            now = time.monotonic()
            # Add tokens based on time elapsed
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_retry_after(self) -> float:
        """Get seconds until a token is available."""
        with self.lock:
            if self.tokens >= 1:
                return 0
            return (1 - self.tokens) / self.rate


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using token bucket algorithm."""

    def __init__(
        self,
        app,
        requests_per_minute: int = 60,
        burst: int = 10,
        enabled: bool = True,
        settings_getter=None,
    ):
        """Initialize rate limiter.

        Args:
            app: FastAPI application
            requests_per_minute: Sustained request rate per client
            burst: Maximum burst size
            enabled: Whether rate limiting is enabled (default, can be overridden by settings)
            settings_getter: Optional callable to get settings dynamically
        """
        super().__init__(app)
        self._default_enabled = enabled
        self._settings_getter = settings_getter
        self.rate = requests_per_minute / 60.0  # Convert to per-second
        self.burst = burst
        self.buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(self.rate, self.burst)
        )
        self.lock = Lock()

    def _is_enabled(self, request: Request) -> bool:
        """Check if rate limiting is enabled for this request.

        Checks for test bypass header or settings override.
        """
        # Allow bypassing rate limits in tests via header
        if request.headers.get("X-Test-Bypass-RateLimit") == "true":
            return False

        if self._settings_getter:
            try:
                settings = self._settings_getter()
                return settings.rate_limit_enabled
            except Exception:
                pass
        return self._default_enabled

    def _get_client_key(self, request: Request) -> str:
        """Get unique client identifier.

        Uses X-Forwarded-For header if present (behind proxy),
        otherwise falls back to client host.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Take the first IP (client's original IP)
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(
        self, request: Request, call_next: Callable
    ) -> Response:
        """Process request with rate limiting."""
        # Skip rate limiting if disabled
        if not self._is_enabled(request):
            return await call_next(request)

        # Skip health/readiness endpoints
        if request.url.path in ("/registry/health", "/registry/ready", "/metrics"):
            return await call_next(request)

        client_key = self._get_client_key(request)

        # Get or create bucket for this client
        with self.lock:
            bucket = self.buckets[client_key]

        if not bucket.consume():
            # Rate limited
            retry_after = int(bucket.get_retry_after()) + 1
            logger.warning(
                "rate_limit_exceeded",
                client=client_key,
                path=request.url.path,
                retry_after=retry_after,
            )

            error_response = ErrorResponse(
                error_code="RATE_LIMIT_EXCEEDED",
                message=f"Rate limit exceeded. Retry after {retry_after} seconds.",
                correlation_id=get_correlation_id(),
            )

            return JSONResponse(
                status_code=429,
                content=error_response.model_dump(exclude_none=True),
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
