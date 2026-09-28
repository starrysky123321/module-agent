import asyncio

import httpx
from fastapi import FastAPI

from module_agent.api.rate_limit import register_api_rate_limit_middleware
from module_agent.shared.config import AppSettings


class FakeRateLimitStore:
    def __init__(self, *, fail: bool = False) -> None:
        self.count = 0
        self.fail = fail

    async def eval(
        self,
        _script: str,
        _numkeys: int,
        *_keys_and_args: str,
    ) -> object:
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.count += 1
        return [self.count, 30]


def _application(
    store: FakeRateLimitStore,
    *, fail_open: bool = False,
) -> FastAPI:
    application = FastAPI()
    settings = AppSettings(
        _env_file=None,
        api_rate_limit_enabled=True,
        api_rate_limit_requests=2,
        api_rate_limit_window_seconds=60,
        api_rate_limit_fail_open=fail_open,
    )
    register_api_rate_limit_middleware(application, settings, store)

    @application.get("/api/work")
    async def work() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/health/")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


def test_rate_limit_rejects_requests_over_the_window_quota() -> None:
    async def send() -> list[httpx.Response]:
        transport = httpx.ASGITransport(
            app=_application(FakeRateLimitStore())
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return [await client.get("/api/work") for _ in range(3)]

    responses = asyncio.run(send())

    assert [response.status_code for response in responses] == [200, 200, 429]
    assert responses[0].headers["X-RateLimit-Remaining"] == "1"
    assert responses[2].headers["Retry-After"] == "30"
    assert responses[2].json()["code"] == "rate_limit_exceeded"


def test_health_probe_is_not_counted_against_rate_limit() -> None:
    store = FakeRateLimitStore()

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=_application(store))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/health/")

    response = asyncio.run(send())

    assert response.status_code == 200
    assert store.count == 0


def test_rate_limit_fails_closed_when_redis_is_unavailable() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=_application(FakeRateLimitStore(fail=True))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/work")

    response = asyncio.run(send())

    assert response.status_code == 503
    assert response.json()["code"] == "rate_limit_unavailable"
