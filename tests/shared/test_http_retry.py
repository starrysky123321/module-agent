import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from module_agent.shared.http.retry import AsyncHttpRetry


@pytest.mark.parametrize("max_attempts", [0, -1])
def test_http_retry_rejects_invalid_max_attempts(max_attempts: int) -> None:
    with pytest.raises(
        ValueError,
        match="max_attempts must be greater than or equal to 1",
    ):
        AsyncHttpRetry(max_attempts=max_attempts)


@pytest.mark.parametrize("base_delay_seconds", [0, -0.1])
def test_http_retry_rejects_invalid_base_delay(
    base_delay_seconds: float,
) -> None:
    with pytest.raises(
        ValueError,
        match="base_delay_seconds must be greater than 0",
    ):
        AsyncHttpRetry(base_delay_seconds=base_delay_seconds)


def test_http_retry_returns_success_without_sleeping() -> None:
    response = httpx.Response(200)
    operation = AsyncMock(return_value=response)
    sleep = AsyncMock()

    async def run() -> httpx.Response:
        with patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            sleep,
        ):
            return await AsyncHttpRetry().execute(operation)

    result = asyncio.run(run())

    assert result is response
    operation.assert_awaited_once_with()
    sleep.assert_not_awaited()


def test_http_retry_uses_exponential_backoff() -> None:
    final_response = httpx.Response(200)
    operation = AsyncMock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(500),
            final_response,
        ]
    )
    sleep = AsyncMock()

    async def run() -> httpx.Response:
        with patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            sleep,
        ):
            return await AsyncHttpRetry(
                max_attempts=4,
                base_delay_seconds=2.0,
            ).execute(operation)

    result = asyncio.run(run())

    assert result is final_response
    assert operation.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [2.0, 4.0]


def test_http_retry_prefers_retry_after_header() -> None:
    final_response = httpx.Response(200)
    operation = AsyncMock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7.5"}),
            final_response,
        ]
    )
    sleep = AsyncMock()

    async def run() -> httpx.Response:
        with patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            sleep,
        ):
            return await AsyncHttpRetry().execute(operation)

    result = asyncio.run(run())

    assert result is final_response
    sleep.assert_awaited_once_with(7.5)


def test_http_retry_stops_after_max_attempts() -> None:
    responses = [httpx.Response(429) for _ in range(4)]
    operation = AsyncMock(side_effect=responses)
    sleep = AsyncMock()

    async def run() -> httpx.Response:
        with patch(
            "module_agent.shared.http.retry.asyncio.sleep",
            sleep,
        ):
            return await AsyncHttpRetry(
                max_attempts=4,
                base_delay_seconds=2.0,
            ).execute(operation)

    result = asyncio.run(run())

    assert result is responses[-1]
    assert operation.await_count == 4
    assert [call.args[0] for call in sleep.await_args_list] == [2.0, 4.0, 8.0]


@pytest.mark.parametrize("value", [None, "invalid", "-1", "nan", "inf"])
def test_parse_retry_after_rejects_unusable_values(value: str | None) -> None:
    assert AsyncHttpRetry._parse_retry_after(value) is None
