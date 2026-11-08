import asyncio
import json
from unittest.mock import AsyncMock

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


def test_default_readiness_includes_the_real_checkpoint_probe():
    assert health_module._DEPENDENCY_PROBES["checkpoint"] is health_module._check_checkpoint


def test_checkpoint_probe_uses_shared_manager(monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr(health_module.postgres_checkpointer_manager, "check_health", probe)
    asyncio.run(health_module._check_checkpoint())
    probe.assert_awaited_once_with()


def test_checkpoint_failure_blocks_readiness_even_when_database_is_healthy(monkeypatch):
    monkeypatch.setattr(health_module, "_DEPENDENCY_PROBES", {"postgres": _healthy, "checkpoint": _unhealthy})
    response = asyncio.run(health_module.readiness())
    assert response.status_code == 503
    assert json.loads(response.body)["dependencies"] == {"postgres": "ok", "checkpoint": "unavailable"}
