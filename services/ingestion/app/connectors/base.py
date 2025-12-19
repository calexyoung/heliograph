"""Base connector class with common functionality."""

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from services.ingestion.app.core.schemas import SearchResult
from shared.utils.logging import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, rate: float, burst: int = 1):
        """Initialize rate limiter.

        Args:
            rate: Requests per second
            burst: Maximum burst size
        """
        self.rate = rate
        self.burst = burst
        self.tokens = burst
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                logger.debug("rate_limit_wait", wait_seconds=wait_time)
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class BaseConnector(ABC):
    """Base class for external API connectors."""

    SOURCE_NAME: str = "unknown"

    def __init__(
        self,
        base_url: str,
        rate_limit: float = 1.0,
        timeout: float = 30.0,
    ):
        """Initialize connector.

        Args:
            base_url: API base URL
            rate_limit: Requests per second
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.rate_limiter = RateLimiter(rate_limit)
        self.timeout = httpx.Timeout(timeout)
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        headers: dict | None = None,
        json: dict | None = None,
    ) -> httpx.Response:
        """Make rate-limited HTTP request.

        Args:
            method: HTTP method
            path: URL path
            params: Query parameters
            headers: Request headers
            json: JSON body

        Returns:
            HTTP response

        Raises:
            httpx.HTTPError: On request failure
        """
        await self.rate_limiter.acquire()

        client = await self.get_client()
        url = f"{self.base_url}{path}"

        response = await client.request(
            method=method,
            url=url,
            params=params,
            headers=headers,
            json=json,
        )

        logger.debug(
            "connector_request",
            source=self.SOURCE_NAME,
            method=method,
            url=url,
            status=response.status_code,
        )

        return response

    async def _get(
        self,
        path: str,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """Make GET request."""
        return await self._request("GET", path, params=params, headers=headers)

    async def _post(
        self,
        path: str,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response:
        """Make POST request."""
        return await self._request("POST", path, json=json, headers=headers)

    @abstractmethod
    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[SearchResult]:
        """Search for papers.

        Args:
            query: Search query
            limit: Maximum results
            **kwargs: Additional search parameters

        Returns:
            List of search results
        """
        pass

    @abstractmethod
    async def get_paper(self, external_id: str) -> SearchResult | None:
        """Get paper details by identifier.

        Args:
            external_id: External identifier

        Returns:
            Paper details or None if not found
        """
        pass

    async def get_pdf_url(self, external_id: str) -> str | None:
        """Get PDF download URL for a paper.

        Args:
            external_id: External identifier

        Returns:
            PDF URL or None if not available
        """
        paper = await self.get_paper(external_id)
        return paper.pdf_url if paper else None
