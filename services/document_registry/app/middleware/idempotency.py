"""Idempotency key middleware for Document Registry service."""

import hashlib
import json
import time
from collections import OrderedDict
from threading import Lock
from typing import Any, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from shared.utils.logging import get_logger

logger = get_logger(__name__)

# Header name for idempotency key
IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"

# Default TTL for cached responses (in seconds)
DEFAULT_TTL = 3600  # 1 hour


class IdempotencyCache:
    """Simple in-memory cache for idempotency responses.

    In production, this should be replaced with Redis or another
    distributed cache for multi-instance support.
    """

    def __init__(self, max_size: int = 10000, ttl: int = DEFAULT_TTL):
        """Initialize cache.

        Args:
            max_size: Maximum number of entries to cache
            ttl: Time-to-live for entries in seconds
        """
        self.max_size = max_size
        self.ttl = ttl
        self.cache: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()
        self.processing: set[str] = set()
        self.lock = Lock()

    def _generate_key(self, idempotency_key: str, method: str, path: str) -> str:
        """Generate cache key from idempotency key and request details."""
        return hashlib.sha256(
            f"{idempotency_key}:{method}:{path}".encode()
        ).hexdigest()

    def _evict_expired(self) -> None:
        """Remove expired entries from cache."""
        now = time.monotonic()
        expired_keys = [
            key for key, (_, timestamp) in self.cache.items()
            if now - timestamp > self.ttl
        ]
        for key in expired_keys:
            del self.cache[key]

    def _evict_oldest(self) -> None:
        """Remove oldest entry if cache is full."""
        if len(self.cache) >= self.max_size:
            self.cache.popitem(last=False)

    def get(
        self,
        idempotency_key: str,
        method: str,
        path: str,
    ) -> dict[str, Any] | None:
        """Get cached response for idempotency key.

        Args:
            idempotency_key: Client-provided idempotency key
            method: HTTP method
            path: Request path

        Returns:
            Cached response data or None if not found/expired
        """
        cache_key = self._generate_key(idempotency_key, method, path)

        with self.lock:
            self._evict_expired()

            if cache_key in self.cache:
                data, timestamp = self.cache[cache_key]
                # Move to end (LRU)
                self.cache.move_to_end(cache_key)
                return data

        return None

    def is_processing(
        self,
        idempotency_key: str,
        method: str,
        path: str,
    ) -> bool:
        """Check if a request with this key is currently being processed.

        Args:
            idempotency_key: Client-provided idempotency key
            method: HTTP method
            path: Request path

        Returns:
            True if request is currently processing
        """
        cache_key = self._generate_key(idempotency_key, method, path)
        with self.lock:
            return cache_key in self.processing

    def start_processing(
        self,
        idempotency_key: str,
        method: str,
        path: str,
    ) -> None:
        """Mark a request as being processed.

        Args:
            idempotency_key: Client-provided idempotency key
            method: HTTP method
            path: Request path
        """
        cache_key = self._generate_key(idempotency_key, method, path)
        with self.lock:
            self.processing.add(cache_key)

    def finish_processing(
        self,
        idempotency_key: str,
        method: str,
        path: str,
        response_data: dict[str, Any],
    ) -> None:
        """Store response and mark processing complete.

        Args:
            idempotency_key: Client-provided idempotency key
            method: HTTP method
            path: Request path
            response_data: Response data to cache
        """
        cache_key = self._generate_key(idempotency_key, method, path)

        with self.lock:
            self.processing.discard(cache_key)
            self._evict_oldest()
            self.cache[cache_key] = (response_data, time.monotonic())

    def cancel_processing(
        self,
        idempotency_key: str,
        method: str,
        path: str,
    ) -> None:
        """Cancel processing without caching (for errors).

        Args:
            idempotency_key: Client-provided idempotency key
            method: HTTP method
            path: Request path
        """
        cache_key = self._generate_key(idempotency_key, method, path)
        with self.lock:
            self.processing.discard(cache_key)


# Global cache instance
_idempotency_cache = IdempotencyCache()


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """Middleware to support idempotent requests.

    Caches responses for requests with an Idempotency-Key header,
    returning cached responses for duplicate requests.

    Only applies to POST and PATCH methods by default.
    """

    def __init__(
        self,
        app,
        cache: IdempotencyCache | None = None,
        enabled: bool = True,
    ):
        """Initialize middleware.

        Args:
            app: FastAPI application
            cache: Optional custom cache (uses global if not provided)
            enabled: Whether idempotency checking is enabled
        """
        super().__init__(app)
        self.cache = cache or _idempotency_cache
        self.enabled = enabled

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with idempotency support."""
        # Skip if disabled
        if not self.enabled:
            return await call_next(request)

        # Only apply to POST and PATCH
        if request.method not in ("POST", "PATCH"):
            return await call_next(request)

        # Check for idempotency key
        idempotency_key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
        if not idempotency_key:
            return await call_next(request)

        method = request.method
        path = request.url.path

        # Check for cached response
        cached = self.cache.get(idempotency_key, method, path)
        if cached:
            logger.info(
                "idempotency_cache_hit",
                idempotency_key=idempotency_key,
                path=path,
            )
            return JSONResponse(
                content=cached["body"],
                status_code=cached["status_code"],
                headers={"X-Idempotency-Replayed": "true"},
            )

        # Check if request is already processing
        if self.cache.is_processing(idempotency_key, method, path):
            logger.warning(
                "idempotency_concurrent_request",
                idempotency_key=idempotency_key,
                path=path,
            )
            return JSONResponse(
                content={
                    "error_code": "CONCURRENT_REQUEST",
                    "message": "A request with this idempotency key is already being processed",
                },
                status_code=409,
            )

        # Mark as processing
        self.cache.start_processing(idempotency_key, method, path)

        try:
            # Process request
            response = await call_next(request)

            # Cache successful responses (2xx and 4xx)
            if 200 <= response.status_code < 500:
                # Read response body
                body = b""
                async for chunk in response.body_iterator:
                    body += chunk

                try:
                    body_json = json.loads(body)
                except json.JSONDecodeError:
                    body_json = {"raw": body.decode("utf-8", errors="replace")}

                self.cache.finish_processing(
                    idempotency_key,
                    method,
                    path,
                    {"body": body_json, "status_code": response.status_code},
                )

                # Return new response with body
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            else:
                # Don't cache 5xx errors - client should retry
                self.cache.cancel_processing(idempotency_key, method, path)
                return response

        except Exception:
            # Cancel processing on error
            self.cache.cancel_processing(idempotency_key, method, path)
            raise
