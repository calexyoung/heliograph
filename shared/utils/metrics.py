"""Prometheus metrics helpers."""

import time
from typing import Any, Callable

from fastapi import Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse


def create_counter(
    name: str,
    description: str,
    labels: list[str] | None = None,
) -> Counter:
    """Create a Prometheus counter metric.

    Args:
        name: Metric name (e.g., 'registry_requests_total')
        description: Human-readable description
        labels: List of label names for the metric
    """
    return Counter(name, description, labels or [])


def create_histogram(
    name: str,
    description: str,
    labels: list[str] | None = None,
    buckets: tuple[float, ...] | None = None,
) -> Histogram:
    """Create a Prometheus histogram metric.

    Args:
        name: Metric name (e.g., 'registry_request_duration_seconds')
        description: Human-readable description
        labels: List of label names for the metric
        buckets: Custom bucket boundaries (defaults to Prometheus defaults)
    """
    if buckets is None:
        buckets = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    return Histogram(name, description, labels or [], buckets=buckets)


# Default metrics for HTTP requests
REQUEST_COUNT = create_counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = create_histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)


class MetricsMiddleware(BaseHTTPMiddleware):
    """Middleware to collect HTTP request metrics."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Response]
    ) -> Response:
        """Process request and record metrics."""
        start_time = time.perf_counter()

        response = await call_next(request)

        # Calculate duration
        duration = time.perf_counter() - start_time

        # Get endpoint path (use route pattern if available)
        endpoint = request.url.path
        if request.scope.get("route"):
            endpoint = request.scope["route"].path

        # Record metrics
        REQUEST_COUNT.labels(
            method=request.method,
            endpoint=endpoint,
            status_code=response.status_code,
        ).inc()

        REQUEST_LATENCY.labels(
            method=request.method,
            endpoint=endpoint,
        ).observe(duration)

        return response


async def metrics_endpoint(request: Request) -> StarletteResponse:
    """Endpoint to expose Prometheus metrics."""
    return StarletteResponse(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )


def setup_metrics(app: Any = None, service_name: str = "") -> None:
    """Setup metrics for a service.

    Args:
        app: FastAPI application instance (optional, for adding middleware)
        service_name: Name of the service for metric prefixes

    Note: This function is a no-op. Middleware should be added during app creation,
    not in lifespan handlers. Use app.add_middleware(MetricsMiddleware) directly.
    """
    # Metrics middleware should be added during app creation, not in lifespan
    # This is kept for backwards compatibility but doesn't add middleware
    pass


class MetricsClient:
    """Simple metrics client for tracking application metrics."""

    def __init__(self, prefix: str = ""):
        """Initialize metrics client with optional prefix."""
        self.prefix = prefix
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}

    def increment(self, name: str, labels: dict[str, str] | None = None, value: int = 1) -> None:
        """Increment a counter metric."""
        full_name = f"{self.prefix}_{name}" if self.prefix else name
        if full_name not in self._counters:
            label_names = list(labels.keys()) if labels else []
            self._counters[full_name] = create_counter(full_name, f"Counter for {name}", label_names)
        if labels:
            self._counters[full_name].labels(**labels).inc(value)
        else:
            self._counters[full_name].inc(value)

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Observe a histogram value."""
        full_name = f"{self.prefix}_{name}" if self.prefix else name
        if full_name not in self._histograms:
            label_names = list(labels.keys()) if labels else []
            self._histograms[full_name] = create_histogram(full_name, f"Histogram for {name}", label_names)
        if labels:
            self._histograms[full_name].labels(**labels).observe(value)
        else:
            self._histograms[full_name].observe(value)
