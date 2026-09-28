import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from module_agent.shared.http.rate_limiter import AsyncRateLimiter


@pytest.mark.parametrize("interval", [0, -0.1])
def test_rate_limiter_rejects_non_positive_interval(interval: float) -> None:
    with pytest.raises(
        ValueError,
        match="min_interval_seconds must be greater than 0",
    ):
        AsyncRateLimiter(interval)


def test_rate_limiter_allows_first_request_without_sleeping() -> None:
    limiter = AsyncRateLimiter(min_interval_seconds=1.0)
    sleep = AsyncMock()

    async def run() -> None:
        with (
            patch(
                "module_agent.shared.http.rate_limiter.time.monotonic",
                side_effect=[10.0, 10.0],
            ),
            patch(
                "module_agent.shared.http.rate_limiter.asyncio.sleep",
                sleep,
            ),
        ):
            await limiter.wait()

    asyncio.run(run())

    sleep.assert_not_awaited()


def test_rate_limiter_sleeps_only_for_remaining_interval() -> None:
    limiter = AsyncRateLimiter(min_interval_seconds=1.0)
    sleep = AsyncMock()

    async def run() -> None:
        with (
            patch(
                "module_agent.shared.http.rate_limiter.time.monotonic",
                side_effect=[10.0, 10.0, 10.25, 11.0],
            ),
            patch(
                "module_agent.shared.http.rate_limiter.asyncio.sleep",
                sleep,
            ),
        ):
            await limiter.wait()
            await limiter.wait()

    asyncio.run(run())

    sleep.assert_awaited_once_with(pytest.approx(0.75))
