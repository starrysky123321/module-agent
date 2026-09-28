import asyncio

import httpx
from fastapi import FastAPI

from module_agent.api.auth import register_api_auth_middleware
from module_agent.shared.config import AppSettings


def production_app() -> FastAPI:
    application = FastAPI()
    settings = AppSettings(
        _env_file=None,
        app_env="production",
        api_auth_token="a-secure-production-token-that-is-long-enough",
    )
    register_api_auth_middleware(application, settings)

    @application.get("/api/private")
    async def private() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/api/health/")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


def test_production_api_requires_bearer_token() -> None:
    async def send() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=production_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            denied = await client.get("/api/private")
            accepted = await client.get(
                "/api/private",
                headers={
                    "Authorization": (
                        "Bearer a-secure-production-token-that-is-long-enough"
                    )
                },
            )
            return denied, accepted

    denied, accepted = asyncio.run(send())

    assert denied.status_code == 401
    assert denied.headers["WWW-Authenticate"] == "Bearer"
    assert accepted.status_code == 200


def test_health_endpoint_remains_public() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=production_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/health/")

    response = asyncio.run(send())

    assert response.status_code == 200
