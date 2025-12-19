"""Service proxy for routing requests to backend services."""

import asyncio
from typing import Any
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException, Request, Response, status

from services.api_gateway.app.config import get_settings
from services.api_gateway.app.routing.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
)
from shared.utils.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


class ServiceProxy:
    """Proxy for routing requests to backend services with circuit breaker."""

    def __init__(self):
        """Initialize service proxy with circuit breakers for each service."""
        self.settings = get_settings()

        # Configure circuit breakers for each service
        cb_config = CircuitBreakerConfig(
            failure_threshold=self.settings.circuit_breaker_failure_threshold,
            recovery_timeout=self.settings.circuit_breaker_recovery_timeout,
            half_open_requests=self.settings.circuit_breaker_half_open_requests,
        )

        self.circuit_breakers = {
            "document-registry": CircuitBreaker("document-registry", cb_config),
            "ingestion": CircuitBreaker("ingestion", cb_config),
            "query-orchestrator": CircuitBreaker("query-orchestrator", cb_config),
            "knowledge-extraction": CircuitBreaker("knowledge-extraction", cb_config),
        }

        self.service_urls = {
            "document-registry": self.settings.document_registry_url,
            "ingestion": self.settings.ingestion_service_url,
            "query-orchestrator": self.settings.query_orchestrator_url,
            "knowledge-extraction": self.settings.knowledge_extraction_url,
        }

        # HTTP client configuration
        self.timeout = httpx.Timeout(30.0, connect=5.0)
        self.limits = httpx.Limits(max_keepalive_connections=20, max_connections=100)

    async def forward_request(
        self,
        service: str,
        path: str,
        request: Request,
        method: str | None = None,
        body: Any | None = None,
        query_params: dict | None = None,
        headers: dict | None = None,
    ) -> Response:
        """Forward a request to a backend service.

        Args:
            service: Target service name
            path: Path on the target service
            request: Original FastAPI request
            method: HTTP method (defaults to request method)
            body: Request body (defaults to reading from request)
            query_params: Query parameters (defaults to request query params)
            headers: Additional headers

        Returns:
            Response from backend service

        Raises:
            HTTPException: If service unavailable or request fails
        """
        if service not in self.service_urls:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unknown service: {service}",
            )

        base_url = self.service_urls[service]
        url = urljoin(base_url, path)
        method = method or request.method

        # Build headers
        forward_headers = self._build_headers(request, headers)

        # Get body if not provided
        if body is None and method in ("POST", "PUT", "PATCH"):
            body = await request.body()

        # Get query params if not provided
        if query_params is None:
            query_params = dict(request.query_params)

        circuit_breaker = self.circuit_breakers[service]

        try:
            response = await circuit_breaker.call(
                self._make_request,
                method=method,
                url=url,
                headers=forward_headers,
                content=body,
                params=query_params,
            )

            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.headers.get("content-type"),
            )

        except CircuitBreakerOpenError as e:
            logger.warning(
                "circuit_breaker_open",
                service=service,
                retry_after=e.retry_after,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Service {service} is temporarily unavailable",
                headers={"Retry-After": str(e.retry_after)},
            )

        except httpx.TimeoutException:
            logger.error("service_timeout", service=service, url=url)
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"Service {service} request timed out",
            )

        except httpx.ConnectError:
            logger.error("service_connect_error", service=service, url=url)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Unable to connect to service {service}",
            )

        except Exception as e:
            logger.exception("service_proxy_error", service=service, error=str(e))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Error communicating with service {service}",
            )

    async def _make_request(
        self,
        method: str,
        url: str,
        headers: dict,
        content: bytes | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """Make HTTP request to backend service.

        Args:
            method: HTTP method
            url: Full URL
            headers: Request headers
            content: Request body
            params: Query parameters

        Returns:
            HTTP response
        """
        async with httpx.AsyncClient(timeout=self.timeout, limits=self.limits) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=content,
                params=params,
            )

            # Log request
            logger.info(
                "service_request",
                method=method,
                url=url,
                status_code=response.status_code,
            )

            return response

    def _build_headers(
        self,
        request: Request,
        extra_headers: dict | None = None,
    ) -> dict:
        """Build headers for forwarded request.

        Args:
            request: Original request
            extra_headers: Additional headers to include

        Returns:
            Headers dict
        """
        # Start with correlation ID
        headers = {
            "X-Correlation-ID": get_correlation_id(),
        }

        # Forward safe headers
        safe_headers = [
            "content-type",
            "accept",
            "accept-language",
            "user-agent",
        ]

        for header in safe_headers:
            value = request.headers.get(header)
            if value:
                headers[header] = value

        # Add user context if authenticated
        if hasattr(request.state, "user") and request.state.user:
            headers["X-User-ID"] = str(request.state.user.user_id)
            headers["X-User-Email"] = request.state.user.email

        # Add extra headers
        if extra_headers:
            headers.update(extra_headers)

        return headers

    def get_circuit_states(self) -> dict:
        """Get current state of all circuit breakers."""
        return {
            name: cb.get_state()
            for name, cb in self.circuit_breakers.items()
        }

    async def reset_circuit(self, service: str) -> bool:
        """Reset a specific circuit breaker.

        Args:
            service: Service name

        Returns:
            True if circuit was reset
        """
        if service in self.circuit_breakers:
            await self.circuit_breakers[service].reset()
            return True
        return False
