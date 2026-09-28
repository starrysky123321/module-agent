from typing import Annotated

from fastapi import APIRouter, Depends, Path

from module_agent.bootstrap.api_dependencies import (
    get_validation_run_service,
    get_module_workflow_service,
)
from module_agent.validation.domain.report import ValidationReport
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.domain import ValidationRun


validation_router = APIRouter(
    prefix="/validation",
    tags=["validation-agent"],
)


@validation_router.get(
    "/runs/{run_id}/reports",
    response_model=list[ValidationReport],
)
async def get_validation_reports(
    run_id: Annotated[int, Path(gt=0)],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> list[ValidationReport]:
    """获取对应记录。"""
    return await workflow_service.get_validation_reports(run_id)


@validation_router.get(
    "/executions/{execution_id}",
    response_model=ValidationRun,
)
async def get_validation_run(
    execution_id: Annotated[int, Path(gt=0)],
    service: Annotated[
        ValidationRunService,
        Depends(get_validation_run_service),
    ],
) -> ValidationRun:
    """获取对应记录。"""
    return await service.get_run(execution_id)


@validation_router.get(
    "/runs/{run_id}/executions",
    response_model=list[ValidationRun],
)
async def list_validation_runs(
    run_id: Annotated[int, Path(gt=0)],
    service: Annotated[
        ValidationRunService,
        Depends(get_validation_run_service),
    ],
) -> list[ValidationRun]:
    """列出符合条件的记录。"""
    return await service.list_runs(run_id)
