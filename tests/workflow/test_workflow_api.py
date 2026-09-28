import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx

from module_agent.bootstrap.api_dependencies import (
    get_module_workflow_service,
    get_workflow_node_execution_repository,
)
from module_agent.main import create_app
from module_agent.shared.exceptions import WorkflowResultNotReadyError
from module_agent.supervision.domain import (
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import SupervisorStep, WorkflowStatus
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunStatus,
)
from module_agent.workflow.result import ModuleBuildResult
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.adapters.database.node_execution import (
    SqlAlchemyWorkflowNodeExecutionRepository,
)
from module_agent.workflow.observation import (
    WorkflowNodeExecution,
    WorkflowNodeExecutionStatus,
    WorkflowRuntimeMetrics,
)
from uuid import uuid4


def send_get(path: str, service: AsyncMock) -> httpx.Response:
    application = create_app()
    application.dependency_overrides[get_module_workflow_service] = (
        lambda: service
    )

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def send_post(
    path: str,
    service: AsyncMock,
    *,
    json: dict[str, object] | None = None,
) -> httpx.Response:
    application = create_app()
    application.dependency_overrides[get_module_workflow_service] = (
        lambda: service
    )

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.post(path, json=json)

    return asyncio.run(request())


def final_failure_result() -> ModuleBuildResult:
    failure = WorkflowFailure(
        step=SupervisorStep.CODE,
        category=WorkflowFailureCategory.INTERNAL,
        message="Code preparation failed",
        retryable=False,
        attempt=1,
        error_type="RuntimeError",
    )
    return ModuleBuildResult(
        literature_run_id=7,
        status=WorkflowStatus.FAILED,
        attempts={SupervisorStep.CODE: 1},
        failure=failure,
    )


def test_workflow_result_endpoint_returns_typed_result() -> None:
    service = AsyncMock(spec=ModuleWorkflowService)
    service.get_result.return_value = final_failure_result()

    response = send_get("/api/workflow/runs/7/result", service)

    assert response.status_code == 200
    assert response.json()["literature_run_id"] == 7
    assert response.json()["status"] == "failed"
    assert response.json()["failure"]["step"] == "code"
    service.get_result.assert_awaited_once_with(7)


def test_workflow_result_endpoint_returns_conflict_while_running() -> None:
    service = AsyncMock(spec=ModuleWorkflowService)
    service.get_result.side_effect = WorkflowResultNotReadyError(
        7,
        WorkflowStatus.VALIDATING.value,
    )

    response = send_get("/api/workflow/runs/7/result", service)

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Workflow result for literature run 7 is not ready",
        "code": "workflow_result_not_ready",
        "details": {
            "run_id": 7,
            "status": "validating",
        },
    }


def test_workflow_result_endpoint_rejects_non_positive_run_id() -> None:
    service = AsyncMock(spec=ModuleWorkflowService)

    response = send_get("/api/workflow/runs/0/result", service)

    assert response.status_code == 422
    service.get_result.assert_not_awaited()


def test_workflow_resume_endpoint_renews_timed_out_wait() -> None:
    service = AsyncMock(spec=ModuleWorkflowService)
    now = datetime.now(timezone.utc)
    resumed = ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=uuid4(),
        status=ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
        deadline_at=now + timedelta(minutes=10),
    )
    service.resume_timed_out.return_value = resumed

    response = send_post(
        "/api/workflow/runs/7/resume",
        service,
        json={"timeout_seconds": 600},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "waiting_for_selection"
    service.resume_timed_out.assert_awaited_once_with(
        7,
        timeout_seconds=600,
    )


def test_workflow_resume_endpoint_validates_timeout() -> None:
    service = AsyncMock(spec=ModuleWorkflowService)

    response = send_post(
        "/api/workflow/runs/7/resume",
        service,
        json={"timeout_seconds": 0},
    )

    assert response.status_code == 422
    service.resume_timed_out.assert_not_awaited()


def test_workflow_node_trace_endpoint_returns_observations() -> None:
    repository = AsyncMock(
        spec=SqlAlchemyWorkflowNodeExecutionRepository
    )
    observation = WorkflowNodeExecution(
        literature_run_id=7,
        trace_id=uuid4(),
        node="code",
        status=WorkflowNodeExecutionStatus.COMPLETED,
        duration_ms=12.5,
    )
    repository.list_by_workflow.return_value = [observation]
    application = create_app()
    application.dependency_overrides[
        get_workflow_node_execution_repository
    ] = lambda: repository

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/workflow/runs/7/nodes")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()[0]["node"] == "code"
    repository.list_by_workflow.assert_awaited_once_with(7)


def test_workflow_metrics_endpoint_returns_runtime_summary() -> None:
    repository = AsyncMock(
        spec=SqlAlchemyWorkflowNodeExecutionRepository
    )
    metrics = WorkflowRuntimeMetrics(
        total_workflows=10,
        status_counts={"completed": 8, "failed": 2},
        success_rate=0.8,
        average_workflow_duration_ms=1000,
        node_executions=50,
        failed_node_executions=2,
        average_node_duration_ms=20,
    )
    repository.metrics.return_value = metrics
    application = create_app()
    application.dependency_overrides[
        get_workflow_node_execution_repository
    ] = lambda: repository

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/workflow/metrics")

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["success_rate"] == 0.8
    repository.metrics.assert_awaited_once_with()
