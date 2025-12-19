"""Correlation ID middleware for request tracing."""

import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shared.utils.logging import set_correlation_id


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Middleware to handle correlation IDs for request tracing."""

    CORRELATION_ID_HEADER = "X-Correlation-ID"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process request with correlation ID.

        Extracts correlation ID from request header or generates a new one.

        Args:
            request: FastAPI request
            call_next: Next middleware/handler

        Returns:
            Response with correlation ID header
        """
        # Get or generate correlation ID
        correlation_id = request.headers.get(self.CORRELATION_ID_HEADER)
        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Set in context for logging
        set_correlation_id(correlation_id)

        # Store in request state for access in handlers
        request.state.correlation_id = correlation_id

        # Process request
        response = await call_next(request)

        # Add correlation ID to response
        response.headers[self.CORRELATION_ID_HEADER] = correlation_id

        return response
