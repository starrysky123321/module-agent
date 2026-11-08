"""HTTP admission and authentication for runtime resource discovery."""

import asyncio

import httpx
from fastapi import FastAPI
import pytest

from module_agent.api.auth import register_api_auth_middleware
from module_agent.api.resources import get_resource_snapshot, resources_router
from module_agent.shared.config import AppSettings
from module_agent.shared.resources import GpuResource, ResourceSnapshot


def snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        scope="container", logical_cpu_count=16, available_cpu_count=2,
        memory_total_mb=4096, memory_available_mb=2048,
        workspace_free_mb=4096, gpu_status="detected", sandbox_ready=True,
        gpus=[GpuResource(index=0, uuid="GPU-test-123", name="Test GPU")],
    )


def send(method: str, path: str, *, budget: dict | None = None, token: bool = True) -> httpx.Response:
    async def request() -> httpx.Response:
        app = FastAPI()
        app.include_router(resources_router, prefix="/api")
        register_api_auth_middleware(app, AppSettings(
            _env_file=None, app_env="production", api_auth_token="resource-test-token-that-is-long-enough",
        ))
        app.dependency_overrides[get_resource_snapshot] = snapshot
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, path, json=budget, headers={"Authorization": "Bearer resource-test-token-that-is-long-enough"} if token else {})

    return asyncio.run(request())


def test_resource_discovery_requires_token_in_production() -> None:
    assert send("GET", "/api/system/resources", token=False).status_code == 401
    response = send("GET", "/api/system/resources")
    assert response.status_code == 200
    assert response.json()["available_cpu_count"] == 2
    assert "api_auth_token" not in response.text


@pytest.mark.parametrize("budget", [
    {"cpu_limit": 3}, {"memory_limit_mb": 4096}, {"workspace_limit_mb": 8192},
    {"workspace_limit_mb": 0}, {"cpu_limit": -1},
    {"mode": "sandbox", "compute_target": "gpu", "gpu_device_ids": ["GPU-other"]},
])
def test_resource_admission_rejects_impossible_or_invalid_budgets(budget: dict) -> None:
    response = send("POST", "/api/system/resources/validate", budget=budget)
    assert response.status_code == 422


def test_valid_budget_and_selected_gpu_are_admitted() -> None:
    response = send("POST", "/api/system/resources/validate", budget={
        "mode": "sandbox", "cpu_limit": 1.5, "memory_limit_mb": 1024,
        "workspace_limit_mb": 2048, "compute_target": "gpu", "gpu_device_ids": ["GPU-test-123"],
    })
    assert response.status_code == 200


def test_sandbox_admission_fails_when_executor_is_not_ready() -> None:
    from module_agent.api.resources import validate_resource_budget
    from module_agent.validation.domain.request import ValidationPolicy
    from fastapi import HTTPException

    resources = snapshot().model_copy(update={"sandbox_ready": False, "sandbox_reason": "Sandbox not configured"})
    with pytest.raises(HTTPException, match="Sandbox not configured"):
        validate_resource_budget(ValidationPolicy(mode="sandbox"), resources)
