import asyncio
import json

from fastapi.responses import JSONResponse

from module_agent.api import health as health_module


async def _healthy() -> None:
    return None


async def _unhealthy() -> None:
    raise ConnectionError("unavailable")


def test_readiness_reports_all_dependencies(monkeypatch) -> None:
    monkeypatch.setattr(
        health_module,
        "_DEPENDENCY_PROBES",
        {"postgres": _healthy, "redis": _healthy},
    )

    result = asyncio.run(health_module.readiness())

    assert result == {
        "status": "ready",
        "service": health_module.app_settings.app_name,
        "dependencies": {"postgres": "ok", "redis": "ok"},
    }


def test_readiness_returns_503_without_leaking_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        health_module,
        "_DEPENDENCY_PROBES",
        {"postgres": _healthy, "redis": _unhealthy},
    )

    result = asyncio.run(health_module.readiness())

    assert isinstance(result, JSONResponse)
    assert result.status_code == 503
    payload = json.loads(result.body)
    assert payload["status"] == "not_ready"
    assert payload["dependencies"]["redis"] == "unavailable"
    assert "ConnectionError" not in result.body.decode()
