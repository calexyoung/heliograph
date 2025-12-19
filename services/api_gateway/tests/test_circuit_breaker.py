"""Tests for circuit breaker."""

import asyncio

import pytest

from services.api_gateway.app.routing.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


class TestCircuitBreaker:
    """Tests for circuit breaker pattern."""

    @pytest.mark.asyncio
    async def test_initial_state_closed(self):
        """Test circuit starts in closed state."""
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_successful_call(self):
        """Test successful call through circuit."""
        cb = CircuitBreaker("test")

        async def success():
            return "success"

        result = await cb.call(success)
        assert result == "success"
        assert cb.stats.successes == 1

    @pytest.mark.asyncio
    async def test_failed_call(self):
        """Test failed call increments failures."""
        cb = CircuitBreaker("test")

        async def failure():
            raise ValueError("test error")

        with pytest.raises(ValueError):
            await cb.call(failure)

        assert cb.stats.failures == 1
        assert cb.state == CircuitState.CLOSED  # Still closed (below threshold)

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        # Fail up to threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(failure)

        assert cb.state == CircuitState.OPEN
        assert cb.stats.failures == 3

    @pytest.mark.asyncio
    async def test_open_circuit_rejects_calls(self):
        """Test open circuit rejects calls."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(failure)

        assert cb.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(CircuitBreakerOpenError) as exc_info:
            await cb.call(failure)

        assert "is open" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_half_open_after_recovery_timeout(self):
        """Test circuit transitions to half-open after recovery timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0,  # Immediate recovery for testing
        )
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(failure)

        assert cb.state == CircuitState.OPEN

        # Wait and check state
        await asyncio.sleep(0.1)
        await cb._check_state()

        assert cb.state == CircuitState.HALF_OPEN

    @pytest.mark.asyncio
    async def test_half_open_success_closes_circuit(self):
        """Test successful calls in half-open close the circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0,
            success_threshold=2,
        )
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        async def success():
            return "success"

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(failure)

        # Transition to half-open
        await asyncio.sleep(0.1)
        await cb._check_state()

        # Successful calls should close circuit
        await cb.call(success)
        await cb.call(success)

        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_half_open_failure_reopens_circuit(self):
        """Test failed call in half-open reopens circuit."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0,
        )
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(failure)

        # Transition to half-open
        await asyncio.sleep(0.1)
        await cb._check_state()
        assert cb.state == CircuitState.HALF_OPEN

        # Failure should reopen
        with pytest.raises(ValueError):
            await cb.call(failure)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_get_state(self):
        """Test getting circuit state."""
        cb = CircuitBreaker("test-circuit")

        state = cb.get_state()

        assert state["name"] == "test-circuit"
        assert state["state"] == "closed"
        assert state["failures"] == 0
        assert state["successes"] == 0

    @pytest.mark.asyncio
    async def test_reset(self):
        """Test resetting circuit."""
        config = CircuitBreakerConfig(failure_threshold=1)
        cb = CircuitBreaker("test", config)

        async def failure():
            raise ValueError("test error")

        # Open the circuit
        with pytest.raises(ValueError):
            await cb.call(failure)

        assert cb.state == CircuitState.OPEN

        # Reset
        await cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb.stats.failures == 0
