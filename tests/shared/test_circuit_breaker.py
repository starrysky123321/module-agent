import asyncio

import pytest

from module_agent.shared.http.circuit_breaker import (
    AsyncCircuitBreaker,
    CircuitOpenError,
)


@pytest.mark.parametrize("failure_threshold", [0, -1])
def test_circuit_breaker_rejects_invalid_failure_threshold(
    failure_threshold: int,
) -> None:
    with pytest.raises(
        ValueError,
        match="failure_threshold must be greater than or equal to 1",
    ):
        AsyncCircuitBreaker(failure_threshold, 60.0)


@pytest.mark.parametrize("recovery_timeout", [0, -0.1])
def test_circuit_breaker_rejects_invalid_recovery_timeout(
    recovery_timeout: float,
) -> None:
    with pytest.raises(
        ValueError,
        match="recovery_timeout_seconds must be greater than 0",
    ):
        AsyncCircuitBreaker(1, recovery_timeout)


def test_circuit_breaker_opens_and_recovers_with_successful_probe() -> None:
    current_time = 10.0
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=60.0,
        clock=lambda: current_time,
    )

    async def run() -> None:
        nonlocal current_time

        await breaker.before_call()
        await breaker.record_failure()

        with pytest.raises(CircuitOpenError):
            await breaker.before_call()

        current_time = 70.0
        await breaker.before_call()
        with pytest.raises(CircuitOpenError):
            await breaker.before_call()

        await breaker.record_success()
        await breaker.before_call()

    asyncio.run(run())


def test_failed_probe_reopens_circuit_for_full_timeout() -> None:
    current_time = 10.0
    breaker = AsyncCircuitBreaker(
        failure_threshold=1,
        recovery_timeout_seconds=60.0,
        clock=lambda: current_time,
    )

    async def run() -> None:
        nonlocal current_time

        await breaker.record_failure()
        current_time = 70.0
        await breaker.before_call()
        await breaker.record_failure()

        current_time = 100.0
        with pytest.raises(CircuitOpenError):
            await breaker.before_call()

        current_time = 130.0
        await breaker.before_call()

    asyncio.run(run())


def test_circuit_breaker_waits_for_configured_failure_threshold() -> None:
    breaker = AsyncCircuitBreaker(
        failure_threshold=2,
        recovery_timeout_seconds=60.0,
    )

    async def run() -> None:
        await breaker.record_failure()
        await breaker.before_call()
        await breaker.record_failure()
        with pytest.raises(CircuitOpenError):
            await breaker.before_call()

    asyncio.run(run())
