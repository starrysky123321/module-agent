import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
from fastapi import FastAPI

from module_agent.bootstrap.api_dependencies import (
    get_module_workflow_service,
)
from module_agent.code.api.router import code_router
from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.main import create_app
from module_agent.workflow.service import ModuleWorkflowService


def make_application(service: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(code_router, prefix="/api")
    application.dependency_overrides[get_module_workflow_service] = (
        lambda: service
    )
    return application


def send_get(application: FastAPI, path: str) -> httpx.Response:
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def test_code_artifact_endpoint_returns_structured_artifacts() -> None:
    artifact = CodeArtifact(
        paper_id=7,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Graph oversmoothing",
            implementation_steps=["Implement propagation layer"],
        ),
    )
    service = MagicMock(spec=ModuleWorkflowService)
    service.get_code_artifacts = AsyncMock(return_value=[artifact])
    application = make_application(service)

    response = send_get(application, "/api/code/runs/12/artifacts")

    assert response.status_code == 200
    assert response.json()[0]["paper_id"] == 7
    assert response.json()[0]["status"] == "reproduction_planned"
    assert response.json()[0]["reproduction_plan"]["research_problem"] == (
        "Graph oversmoothing"
    )
    service.get_code_artifacts.assert_awaited_once_with(12)


def test_code_artifact_endpoint_returns_empty_list() -> None:
    service = MagicMock(spec=ModuleWorkflowService)
    service.get_code_artifacts = AsyncMock(return_value=[])
    application = make_application(service)

    response = send_get(application, "/api/code/runs/12/artifacts")

    assert response.status_code == 200
    assert response.json() == []


def test_code_artifact_endpoint_rejects_non_positive_run_id() -> None:
    service = MagicMock(spec=ModuleWorkflowService)
    service.get_code_artifacts = AsyncMock(return_value=[])
    application = make_application(service)

    response = send_get(application, "/api/code/runs/0/artifacts")

    assert response.status_code == 422
    service.get_code_artifacts.assert_not_awaited()


def test_main_application_registers_code_artifact_route() -> None:
    service = MagicMock(spec=ModuleWorkflowService)
    service.get_code_artifacts = AsyncMock(return_value=[])
    application = create_app()
    application.dependency_overrides[get_module_workflow_service] = (
        lambda: service
    )

    response = send_get(application, "/api/code/runs/21/artifacts")

    assert response.status_code == 200
    assert response.json() == []
    service.get_code_artifacts.assert_awaited_once_with(21)
