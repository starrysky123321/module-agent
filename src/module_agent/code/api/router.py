from typing import Annotated

from fastapi import APIRouter, Depends, Path

from module_agent.bootstrap.api_dependencies import (
    get_code_run_service,
    get_module_workflow_service,
)
from module_agent.code.domain.artifact import CodeArtifact
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.code.application.run import CodeRunService
from module_agent.code.domain import CodeRun


code_router = APIRouter(
    prefix="/code",
    tags=["code-agent"],
)


@code_router.get(
    "/runs/{run_id}/artifacts",
    response_model=list[CodeArtifact],
)
async def get_code_artifacts(
    run_id: Annotated[int, Path(gt=0)],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> list[CodeArtifact]:
    """获取对应记录。"""
    return await workflow_service.get_code_artifacts(run_id)


@code_router.get(
    "/executions/{execution_id}",
    response_model=CodeRun,
)
async def get_code_run(
    execution_id: Annotated[int, Path(gt=0)],
    service: Annotated[
        CodeRunService,
        Depends(get_code_run_service),
    ],
) -> CodeRun:
    """获取对应记录。"""
    return await service.get_run(execution_id)


@code_router.get(
    "/runs/{run_id}/executions",
    response_model=list[CodeRun],
)
async def list_code_runs(
    run_id: Annotated[int, Path(gt=0)],
    service: Annotated[
        CodeRunService,
        Depends(get_code_run_service),
    ],
) -> list[CodeRun]:
    """列出符合条件的记录。"""
    return await service.list_runs(run_id)
