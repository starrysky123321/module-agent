from typing import Annotated

from fastapi import APIRouter, Depends, Path

from module_agent.bootstrap.api_dependencies import (
    get_module_workflow_service,
    get_workflow_node_execution_repository,
)
from module_agent.workflow.result import ModuleBuildResult
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    WorkflowResumeRequest,
)
from module_agent.workflow.observation import (
    WorkflowNodeExecution,
    WorkflowRuntimeMetrics,
)
from module_agent.workflow.adapters.database.node_execution import (
    SqlAlchemyWorkflowNodeExecutionRepository,
)


workflow_router = APIRouter(
    prefix="/workflow",
    tags=["module-workflow"],
)


@workflow_router.get(
    "/metrics",
    response_model=WorkflowRuntimeMetrics,
)
async def get_workflow_runtime_metrics(
    repository: Annotated[
        SqlAlchemyWorkflowNodeExecutionRepository,
        Depends(get_workflow_node_execution_repository),
    ],
) -> WorkflowRuntimeMetrics:
    """获取对应记录。"""
    return await repository.metrics()


@workflow_router.get(
    "/runs/{run_id}/nodes",
    response_model=list[WorkflowNodeExecution],
)
async def list_workflow_node_executions(
    run_id: Annotated[int, Path(gt=0)],
    repository: Annotated[
        SqlAlchemyWorkflowNodeExecutionRepository,
        Depends(get_workflow_node_execution_repository),
    ],
) -> list[WorkflowNodeExecution]:
    """列出符合条件的记录。"""
    return await repository.list_by_workflow(run_id)


@workflow_router.get(
    "/runs/{run_id}/result",
    response_model=ModuleBuildResult,
)
async def get_module_build_result(
    run_id: Annotated[int, Path(gt=0)],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> ModuleBuildResult:
    """获取对应记录。"""
    return await workflow_service.get_result(run_id)


@workflow_router.get(
    "/runs/{run_id}",
    response_model=ModuleWorkflowRun,
)
async def get_module_workflow_run(
    run_id: Annotated[int, Path(gt=0)],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> ModuleWorkflowRun:
    """获取对应记录。"""
    return await workflow_service.get_lifecycle(run_id)


@workflow_router.post(
    "/runs/{run_id}/cancel",
    response_model=ModuleWorkflowRun,
)
async def cancel_module_workflow(
    run_id: Annotated[int, Path(gt=0)],
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> ModuleWorkflowRun:
    """取消当前流程。"""
    return await workflow_service.cancel(run_id)


@workflow_router.post(
    "/runs/{run_id}/resume",
    response_model=ModuleWorkflowRun,
)
async def resume_timed_out_module_workflow(
    run_id: Annotated[int, Path(gt=0)],
    request: WorkflowResumeRequest,
    workflow_service: Annotated[
        ModuleWorkflowService,
        Depends(get_module_workflow_service),
    ],
) -> ModuleWorkflowRun:
    """恢复暂停的流程。"""
    return await workflow_service.resume_timed_out(
        run_id,
        timeout_seconds=request.timeout_seconds,
    )
