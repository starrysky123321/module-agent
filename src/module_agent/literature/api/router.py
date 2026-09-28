from fastapi import APIRouter, Depends, status
from typing import Annotated

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.bootstrap.api_dependencies import get_literature_agent
from module_agent.literature.domain.search import LiteratureBundle, SearchRequest
from module_agent.literature.domain.run import LiteratureRun
from module_agent.bootstrap.api_dependencies import get_literature_run_service
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.api.schemas import LiteratureDispatchResponse
from module_agent.bootstrap.api_dependencies import get_literature_run_dispatcher
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.literature.application.result import LiteratureResultService
from module_agent.bootstrap.api_dependencies import get_literature_result_service
from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.literature.domain.selection import PaperSelection
from module_agent.workflow.domain import (
    LiteratureWaitInterrupt,
    ModuleWorkflowStartRequest,
    PaperSelectionInterrupt,
    PaperSelectionRequest,
    PaperSelectionStartRequest,
)
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.bootstrap.api_dependencies import get_module_workflow_coordinator



literature_router = APIRouter(
    prefix="/literature",
    tags=["literature-agent"],
)


@literature_router.post(
    "/runs/{run_id}/workflow/start",
    response_model=LiteratureWaitInterrupt,
)
async def start_module_workflow(
    run_id: int,
    request: ModuleWorkflowStartRequest,
    coordinator: Annotated[
        ModuleWorkflowCoordinator,
        Depends(get_module_workflow_coordinator),
    ],
) -> LiteratureWaitInterrupt:
    """启动当前流程。"""
    validation_policy = (
        request.validation_policy
        if "validation_policy" in request.model_fields_set
        else None
    )
    if (
        validation_policy is None
        and request.sandbox_options is None
        and request.validation_requirements is None
        and request.workflow_timeout_seconds is None
        and request.compute_target.value == "cpu"
    ):
        return await coordinator.start_literature_workflow(
            run_id=run_id,
            code_requirements=request.code_requirements,
        )

    return await coordinator.start_literature_workflow(
        run_id=run_id,
        code_requirements=request.code_requirements,
        validation_policy=validation_policy,
        sandbox_options=request.sandbox_options,
        validation_requirements=request.validation_requirements,
        workflow_timeout_seconds=request.workflow_timeout_seconds,
        compute_target=request.compute_target,
    )


@literature_router.post(
    "/runs/{run_id}/workflow/literature/resume",
    response_model=PaperSelectionInterrupt,
)
async def resume_module_workflow_after_literature(
    run_id: int,
    coordinator: Annotated[
        ModuleWorkflowCoordinator,
        Depends(get_module_workflow_coordinator),
    ],
) -> PaperSelectionInterrupt:
    """恢复暂停的流程。"""
    return await coordinator.resume_after_literature_completion(run_id)


@literature_router.post("/runs/{run_id}/selection", response_model=PaperSelection, status_code=status.HTTP_201_CREATED,)
async def selection(
    run_id: int,
    request: PaperSelectionRequest,
    coordinator: Annotated[
        ModuleWorkflowCoordinator,
        Depends(get_module_workflow_coordinator),
    ],
) -> PaperSelection:
    """接收并确认用户提交的论文选择。"""
    return await coordinator.confirm_paper_selection(run_id, request)


@literature_router.post("/search", response_model=LiteratureBundle)
async def search(
    request: SearchRequest,
    agent: Annotated[LiteratureAgent, Depends(get_literature_agent)],
) -> LiteratureBundle:
    """搜索符合条件的结果。"""
    return await agent.run(request)
    
    
@literature_router.post(
    "/runs",
    response_model=LiteratureRun,
    status_code=status.HTTP_201_CREATED,
)
async def create_run(
    request: SearchRequest,
    run_service: Annotated[LiteratureRunService, Depends(get_literature_run_service)],
) -> LiteratureRun:
    """创建对应记录。"""
    return await run_service.create_run(request)


@literature_router.get(
    "/runs/{run_id}",
    response_model=LiteratureRun,
)
async def get_run(
    run_id: int,
    run_service: Annotated[LiteratureRunService, Depends(get_literature_run_service)],
) -> LiteratureRun:
    """获取对应记录。"""
    return await run_service.get_run(run_id)


@literature_router.post(
    "/runs/{run_id}/enqueue",
    response_model=LiteratureDispatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_run(
      run_id: int,
      dispatcher: Annotated[
          LiteratureRunDispatcher,
          Depends(get_literature_run_dispatcher),
      ],
  ) -> LiteratureDispatchResponse:
      """把指定文献任务发送到 RabbitMQ。"""
      message_id = await dispatcher.dispatch(run_id)

      return LiteratureDispatchResponse(
          run_id=run_id,
          message_id=message_id,
      )
      
@literature_router.get(
    "/runs/{run_id}/papers",
    response_model=list[LiteraturePaperRecommendation],
)
async def get_run_papers(
    run_id: int,
    result_service: Annotated[
        LiteratureResultService,
        Depends(get_literature_result_service),
    ],
) -> list[LiteraturePaperRecommendation]:
    """获取对应记录。"""
    return await result_service.get_papers(run_id)



@literature_router.post(
    "/runs/{run_id}/selection/start",
    response_model=PaperSelectionInterrupt,
)
async def start_paper_selection(
    run_id: int,
    request: PaperSelectionStartRequest,
    coordinator: Annotated[
        ModuleWorkflowCoordinator,
        Depends(get_module_workflow_coordinator),
    ],
) -> PaperSelectionInterrupt:
    """启动当前流程。"""
    validation_policy = (
        request.validation_policy
        if "validation_policy" in request.model_fields_set
        else None
    )
    if (
        validation_policy is None
        and request.sandbox_options is None
        and request.validation_requirements is None
        and request.workflow_timeout_seconds is None
        and request.compute_target.value == "cpu"
    ):
        return await coordinator.start_paper_selection(
            run_id=run_id,
            code_requirements=request.code_requirements,
        )

    return await coordinator.start_paper_selection(
        run_id=run_id,
        code_requirements=request.code_requirements,
        validation_policy=validation_policy,
        sandbox_options=request.sandbox_options,
        validation_requirements=request.validation_requirements,
        workflow_timeout_seconds=request.workflow_timeout_seconds,
        compute_target=request.compute_target,
    )
