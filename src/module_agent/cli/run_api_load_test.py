"""Run a bounded API pressure or soak check and print a JSON report."""

import argparse
import asyncio
from dataclasses import asdict, dataclass, field
import json
import math
import os
from pathlib import Path
import random
from time import perf_counter

import httpx


@dataclass(frozen=True)
class LoadTestConfig:
    """Safe bounds and pass criteria for one load-test invocation."""

    base_url: str
    path: str = "/api/health/"
    concurrency: int = 10
    requests: int | None = 100
    duration_seconds: float | None = None
    timeout_seconds: float = 10.0
    max_error_rate: float = 0.01
    max_p95_ms: float = 1000.0

    def __post_init__(self) -> None:
        if not 1 <= self.concurrency <= 1000:
            raise ValueError("concurrency must be between 1 and 1000")
        if self.requests is not None and self.requests < 1:
            raise ValueError("requests must be positive")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.requests is not None and self.duration_seconds is not None:
            raise ValueError("choose requests or duration_seconds, not both")
        if not 0 <= self.max_error_rate <= 1:
            raise ValueError("max_error_rate must be between 0 and 1")
        if self.max_p95_ms <= 0 or self.timeout_seconds <= 0:
            raise ValueError("timeouts and latency thresholds must be positive")


@dataclass
class LoadTestReport:
    """Aggregate results without retaining response bodies or secrets."""

    total: int = 0
    succeeded: int = 0
    http_failures: int = 0
    transport_failures: int = 0
    elapsed_seconds: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    requests_per_second: float = 0.0
    error_rate: float = 0.0
    passed: bool = False
    _latencies_ms: list[float] = field(default_factory=list, repr=False)

    def record_latency(self, latency_ms: float) -> None:
        """Maintain a bounded reservoir for percentile calculation."""
        self.max_ms = max(self.max_ms, latency_ms)
        sample_limit = 100_000
        if len(self._latencies_ms) < sample_limit:
            self._latencies_ms.append(latency_ms)
            return
        replacement = random.randrange(self.total)
        if replacement < sample_limit:
            self._latencies_ms[replacement] = latency_ms

    def finish(self, config: LoadTestConfig, elapsed_seconds: float) -> None:
        self.elapsed_seconds = elapsed_seconds
        failures = self.http_failures + self.transport_failures
        self.error_rate = failures / self.total if self.total else 1.0
        self.requests_per_second = (
            self.total / elapsed_seconds if elapsed_seconds else 0.0
        )
        if self._latencies_ms:
            ordered = sorted(self._latencies_ms)
            index = max(math.ceil(len(ordered) * 0.95) - 1, 0)
            self.p95_ms = ordered[index]
        self.passed = (
            self.total > 0
            and self.error_rate <= config.max_error_rate
            and self.p95_ms <= config.max_p95_ms
        )

    def to_json(self) -> str:
        payload = asdict(self)
        payload.pop("_latencies_ms", None)
        return json.dumps(payload, indent=2, sort_keys=True)


async def run_load_test(
    config: LoadTestConfig,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    token: str = "",
) -> LoadTestReport:
    """Exercise one idempotent GET endpoint with bounded concurrency."""
    report = LoadTestReport()
    next_request = 0
    deadline = (
        perf_counter() + config.duration_seconds
        if config.duration_seconds is not None
        else None
    )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    url = f"{config.base_url.rstrip('/')}/{config.path.lstrip('/')}"
    started = perf_counter()

    async with httpx.AsyncClient(
        transport=transport,
        timeout=config.timeout_seconds,
        limits=httpx.Limits(
            max_connections=config.concurrency,
            max_keepalive_connections=config.concurrency,
        ),
        headers=headers,
        follow_redirects=False,
    ) as client:

        async def worker() -> None:
            nonlocal next_request
            while True:
                if deadline is not None:
                    if perf_counter() >= deadline:
                        return
                else:
                    assert config.requests is not None
                    if next_request >= config.requests:
                        return
                    next_request += 1

                request_started = perf_counter()
                try:
                    response = await client.get(url)
                except httpx.HTTPError:
                    report.transport_failures += 1
                else:
                    if response.is_success:
                        report.succeeded += 1
                    else:
                        report.http_failures += 1
                finally:
                    report.total += 1
                    report.record_latency(
                        (perf_counter() - request_started) * 1000
                    )

        await asyncio.gather(
            *(worker() for _ in range(config.concurrency))
        )

    report.finish(config, perf_counter() - started)
    return report


def _read_api_token() -> str:
    direct = os.getenv("API_AUTH_TOKEN", "").strip()
    secret_file = os.getenv("API_AUTH_TOKEN_FILE", "").strip()
    if direct and secret_file:
        raise ValueError(
            "configure only API_AUTH_TOKEN or API_AUTH_TOKEN_FILE"
        )
    if secret_file:
        return Path(secret_file).read_text(encoding="utf-8").strip()
    return direct


def _parse_args() -> LoadTestConfig:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--path", default="/api/health/")
    parser.add_argument("--concurrency", type=int, default=10)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--requests", type=int)
    mode.add_argument("--duration-seconds", type=float)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--max-error-rate", type=float, default=0.01)
    parser.add_argument("--max-p95-ms", type=float, default=1000.0)
    args = parser.parse_args()
    requests = args.requests
    if requests is None and args.duration_seconds is None:
        requests = 100
    return LoadTestConfig(
        base_url=args.base_url,
        path=args.path,
        concurrency=args.concurrency,
        requests=requests,
        duration_seconds=args.duration_seconds,
        timeout_seconds=args.timeout_seconds,
        max_error_rate=args.max_error_rate,
        max_p95_ms=args.max_p95_ms,
    )


def main() -> None:
    config = _parse_args()
    report = asyncio.run(run_load_test(config, token=_read_api_token()))
    print(report.to_json())
    if not report.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
