"""The destructive task endpoint is authenticated, validated and explicit."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from module_agent.api.auth import register_api_auth_middleware
from module_agent.api.exception_handlers import register_exception_handlers
from module_agent.bootstrap.api_dependencies import get_task_deletion_service
from module_agent.literature.api.router import literature_router
from module_agent.shared.config import AppSettings
from module_agent.shared.exceptions import AppException
from module_agent.workflow.deletion import TaskDeletionService


def send(run_id="9", *, token=True, error=None):
    service = AsyncMock(spec=TaskDeletionService)
    service.delete.side_effect = error
    app = FastAPI()
    app.include_router(literature_router, prefix="/api")
    app.dependency_overrides[get_task_deletion_service] = lambda: service
    register_exception_handlers(app)
    register_api_auth_middleware(app, AppSettings(
        _env_file=None, app_env="production", api_auth_token="test-task-deletion-token-that-is-long-enough",
    ))

    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.delete(f"/api/literature/runs/{run_id}", headers={"Authorization": "Bearer test-task-deletion-token-that-is-long-enough"} if token else {})

    return asyncio.run(request()), service


def test_deletion_requires_authentication():
    response, service = send(token=False)
    assert response.status_code == 401
    service.delete.assert_not_awaited()


@pytest.mark.parametrize("run_id", ["0", "-1", "invalid"])
def test_invalid_identifiers_never_reach_deletion(run_id):
    response, service = send(run_id)
    assert response.status_code == 422
    service.delete.assert_not_awaited()


def test_success_returns_empty_204():
    response, service = send()
    assert response.status_code == 204 and not response.content
    service.delete.assert_awaited_once_with(9)


def test_active_task_conflict_is_preserved():
    response, _ = send(error=AppException("任务仍在执行", "task_is_active", 409))
    assert response.status_code == 409
    assert response.json()["code"] == "task_is_active"
