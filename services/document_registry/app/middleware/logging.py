"""Request/response logging middleware for Document Registry service."""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shared.utils.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


def _get_client_ip(request: Request) -> str:
    """Extract client IP address from request."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware for structured request/response logging.

    Logs request start and completion with timing and context.
    """

    def __init__(
        self,
        app,
        enabled: bool = True,
        exclude_paths: list[str] | None = None,
    ):
        """Initialize middleware.

        Args:
            app: FastAPI application
            enabled: Whether logging is enabled
            exclude_paths: Paths to exclude from logging (e.g., health checks)
        """
        super().__init__(app)
        self.enabled = enabled
        self.exclude_paths = exclude_paths or ["/health", "/ready", "/metrics"]

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with logging."""
        if not self.enabled:
            return await call_next(request)

        # Skip excluded paths
        path = request.url.path
        if any(path.endswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)

        # Gather request context
        correlation_id = get_correlation_id()
        client_ip = _get_client_ip(request)
        method = request.method
        user_agent = request.headers.get("User-Agent", "")[:100]  # Truncate

        # Log request start
        logger.info(
            "request_started",
            correlation_id=correlation_id,
            method=method,
            path=path,
            client_ip=client_ip,
            user_agent=user_agent,
        )

        # Time the request
        start_time = time.perf_counter()

        try:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - start_time) * 1000

            # Log request completion
            log_method = logger.info if response.status_code < 400 else logger.warning
            log_method(
                "request_completed",
                correlation_id=correlation_id,
                method=method,
                path=path,
                status_code=response.status_code,
                duration_ms=round(duration_ms, 2),
                client_ip=client_ip,
            )

            return response

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "request_failed",
                correlation_id=correlation_id,
                method=method,
                path=path,
                duration_ms=round(duration_ms, 2),
                client_ip=client_ip,
                error=str(e),
                error_type=type(e).__name__,
            )
            raise
