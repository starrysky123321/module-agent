import asyncio
from unittest.mock import AsyncMock

import httpx

from module_agent.bootstrap.api_dependencies import (
    get_module_workflow_service,
)
from module_agent.code.domain.artifact import (
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.main import create_app
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationStatus,
)
from module_agent.workflow.service import ModuleWorkflowService


def test_validation_api_returns_checkpoint_reports() -> None:
    report = ValidationReport(
        literature_run_id=7,
        paper_id=51,
        artifact_origin=CodeArtifactOrigin.AUTHOR,
        artifact_status=CodeArtifactStatus.REPOSITORY_READY,
        mode=ValidationMode.STATIC,
        status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.WORKSPACE,
                status=ValidationCheckStatus.PASSED,
                summary="Workspace exists",
            )
        ],
    )
    service = AsyncMock(spec=ModuleWorkflowService)
    service.get_validation_reports.return_value = [report]
    application = create_app()
    application.dependency_overrides[get_module_workflow_service] = (
        lambda: service
    )

    async def request_reports() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/api/validation/runs/7/reports")

    response = asyncio.run(request_reports())

    assert response.status_code == 200
    assert response.json() == [report.model_dump(mode="json")]
    service.get_validation_reports.assert_awaited_once_with(7)
