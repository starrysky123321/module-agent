import asyncio

import httpx
import pytest

from module_agent.cli.run_api_load_test import (
    LoadTestConfig,
    run_load_test,
)


def test_load_test_collects_success_and_latency_metrics() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    config = LoadTestConfig(
        base_url="http://test",
        requests=12,
        concurrency=3,
        max_p95_ms=1000,
    )
    report = asyncio.run(
        run_load_test(config, transport=httpx.MockTransport(handle))
    )

    assert report.total == 12
    assert report.succeeded == 12
    assert report.http_failures == 0
    assert report.passed is True
    assert report.requests_per_second > 0


def test_load_test_fails_when_http_error_rate_exceeds_threshold() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    config = LoadTestConfig(
        base_url="http://test",
        requests=2,
        max_error_rate=0,
    )
    report = asyncio.run(
        run_load_test(config, transport=httpx.MockTransport(handle))
    )

    assert report.http_failures == 2
    assert report.error_rate == 1
    assert report.passed is False


def test_load_test_rejects_unbounded_or_conflicting_inputs() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        LoadTestConfig(base_url="http://test", concurrency=0)
    with pytest.raises(ValueError, match="choose requests"):
        LoadTestConfig(
            base_url="http://test",
            requests=10,
            duration_seconds=5,
        )
