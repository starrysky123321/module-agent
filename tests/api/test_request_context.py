import asyncio

import httpx
from fastapi import FastAPI

from module_agent.api.request_context import (
    register_request_context_middleware,
)
from module_agent.shared.context import request_id_ctx_var


def _app() -> FastAPI:
    application = FastAPI()
    register_request_context_middleware(application)

    @application.get("/context")
    async def context() -> dict[str, str]:
        return {"request_id": request_id_ctx_var.get()}

    return application


def test_request_id_is_propagated_to_context_and_response() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(
                "/context",
                headers={"X-Request-ID": "request-42"},
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "request-42"
    assert response.json() == {"request_id": "request-42"}


def test_unsafe_request_id_is_replaced() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=_app())
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(
                "/context",
                headers={"X-Request-ID": "unsafe/value"},
            )

    response = asyncio.run(send())

    request_id = response.headers["X-Request-ID"]
    assert len(request_id) == 32
    assert response.json() == {"request_id": request_id}
