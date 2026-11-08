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
    report = asyncio.run(run_load_test(config, transport=httpx.MockTransport(handle)))

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
    report = asyncio.run(run_load_test(config, transport=httpx.MockTransport(handle)))

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


@pytest.mark.parametrize(
    "field", ["duration_seconds", "timeout_seconds", "max_p95_ms", "target_rps"]
)
@pytest.mark.parametrize("value", [float("inf"), float("nan"), 0, -1])
def test_load_test_rejects_nonfinite_or_nonpositive_limits(field, value):
    config = {"base_url": "http://test", field: value}
    if field == "duration_seconds":
        config["requests"] = None
    with pytest.raises(ValueError):
        LoadTestConfig(**config)


def test_load_test_rejects_neither_count_nor_duration():
    with pytest.raises(ValueError, match="unbounded"):
        LoadTestConfig(base_url="http://test", requests=None)


def test_rate_cap_applies_globally_and_status_counts_remain_visible():
    import time

    starts = []

    async def handler(_):
        starts.append(time.perf_counter())
        return httpx.Response(200 if len(starts) % 2 else 429)

    config = LoadTestConfig(
        base_url="http://test", requests=4, concurrency=4, target_rps=20
    )
    report = asyncio.run(run_load_test(config, transport=httpx.MockTransport(handler)))
    assert report.total == 4 and report.status_counts == {200: 2, 429: 2}
    assert starts[-1] - starts[0] >= 0.1
    assert report.p50_ms <= report.p95_ms <= report.p99_ms
