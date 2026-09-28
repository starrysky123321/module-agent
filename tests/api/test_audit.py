import asyncio
from unittest.mock import MagicMock

import httpx
from fastapi import FastAPI

from module_agent.api import audit


def test_audit_middleware_records_request_without_token_value(
    monkeypatch,
) -> None:
    audit_logger = MagicMock()
    monkeypatch.setattr(audit, "logger", audit_logger)
    application = FastAPI()

    @application.middleware("http")
    async def authenticate(request, call_next):
        request.state.authenticated = True
        return await call_next(request)

    audit.register_audit_middleware(application)

    @application.get("/work")
    async def work() -> dict[str, str]:
        return {"status": "ok"}

    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(
                "/work",
                headers={"Authorization": "Bearer do-not-log-this"},
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    logged = repr(audit_logger.info.call_args)
    assert "principal=api_token" not in logged
    assert "do-not-log-this" not in logged
    assert audit_logger.info.call_args.args[5] == "api_token"
