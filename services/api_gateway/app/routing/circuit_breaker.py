"""Circuit breaker pattern implementation."""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeVar

from shared.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failures exceeded threshold, rejecting calls
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 5  # Failures before opening
    recovery_timeout: int = 30  # Seconds before trying half-open
    half_open_requests: int = 3  # Requests to allow in half-open
    success_threshold: int = 2  # Successes in half-open to close


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""

    failures: int = 0
    successes: int = 0
    last_failure_time: float = 0
    last_success_time: float = 0
    half_open_successes: int = 0
    half_open_failures: int = 0


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures."""

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ):
        """Initialize circuit breaker.

        Args:
            name: Name of the circuit (for logging/metrics)
            config: Circuit breaker configuration
        """
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self.state = CircuitState.CLOSED
        self.stats = CircuitStats()
        self._lock = asyncio.Lock()
        self._half_open_requests = 0

    async def call(
        self,
        func: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        """Execute function through circuit breaker.

        Args:
            func: Async function to call
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Function result

        Raises:
            CircuitBreakerOpen: If circuit is open
            Exception: If function raises and circuit records failure
        """
        async with self._lock:
            await self._check_state()

            if self.state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    f"Circuit {self.name} is open",
                    retry_after=self._time_until_recovery(),
                )

            if self.state == CircuitState.HALF_OPEN:
                if self._half_open_requests >= self.config.half_open_requests:
                    raise CircuitBreakerOpenError(
                        f"Circuit {self.name} is half-open, max requests reached",
                        retry_after=1,
                    )
                self._half_open_requests += 1

        try:
            result = await func(*args, **kwargs)
            await self._record_success()
            return result
        except Exception as e:
            await self._record_failure()
            raise

    async def _check_state(self) -> None:
        """Check and update circuit state based on timing."""
        if self.state == CircuitState.OPEN:
            if self._time_since_last_failure() >= self.config.recovery_timeout:
                logger.info(
                    "circuit_half_open",
                    circuit=self.name,
                )
                self.state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                self.stats.half_open_successes = 0
                self.stats.half_open_failures = 0

    async def _record_success(self) -> None:
        """Record a successful call."""
        async with self._lock:
            self.stats.successes += 1
            self.stats.last_success_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.stats.half_open_successes += 1
                if self.stats.half_open_successes >= self.config.success_threshold:
                    logger.info(
                        "circuit_closed",
                        circuit=self.name,
                        half_open_successes=self.stats.half_open_successes,
                    )
                    self.state = CircuitState.CLOSED
                    self.stats.failures = 0

    async def _record_failure(self) -> None:
        """Record a failed call."""
        async with self._lock:
            self.stats.failures += 1
            self.stats.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.stats.half_open_failures += 1
                logger.warning(
                    "circuit_open",
                    circuit=self.name,
                    reason="half_open_failure",
                )
                self.state = CircuitState.OPEN

            elif self.state == CircuitState.CLOSED:
                if self.stats.failures >= self.config.failure_threshold:
                    logger.warning(
                        "circuit_open",
                        circuit=self.name,
                        failures=self.stats.failures,
                    )
                    self.state = CircuitState.OPEN

    def _time_since_last_failure(self) -> float:
        """Get seconds since last failure."""
        if self.stats.last_failure_time == 0:
            return float("inf")
        return time.time() - self.stats.last_failure_time

    def _time_until_recovery(self) -> int:
        """Get seconds until circuit can try recovery."""
        elapsed = self._time_since_last_failure()
        return max(0, int(self.config.recovery_timeout - elapsed))

    def get_state(self) -> dict:
        """Get current circuit state for monitoring."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.stats.failures,
            "successes": self.stats.successes,
            "last_failure": self.stats.last_failure_time,
            "recovery_in": self._time_until_recovery() if self.state == CircuitState.OPEN else None,
        }

    async def reset(self) -> None:
        """Manually reset the circuit breaker."""
        async with self._lock:
            self.state = CircuitState.CLOSED
            self.stats = CircuitStats()
            logger.info("circuit_reset", circuit=self.name)


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, message: str, retry_after: int = 0):
        self.message = message
        self.retry_after = retry_after
        super().__init__(message)
