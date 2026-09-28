from module_agent.shared.exceptions import LiteratureRunStateError
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.domain.selection import PaperSelection
from module_agent.workflow.domain import (
    LiteratureWaitInterrupt,
    PaperSelectionInterrupt,
    PaperSelectionRequest,
)
from module_agent.literature.application.run import LiteratureRunService
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.literature.application.selection import PaperSelectionService
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationPolicy,
)
from module_agent.code.domain.jobs import ComputeTarget


class ModuleWorkflowCoordinator:
    """封装 ModuleWorkflowCoordinator 相关的数据和行为。"""
    def __init__(
        self,
        workflow_service: ModuleWorkflowService,
        run_service: LiteratureRunService,
        selection_service: PaperSelectionService,
    ) -> None:
        """初始化当前对象。"""
        self.workflow_service = workflow_service
        self.run_service = run_service
        self.selection_service = selection_service

    async def start_literature_workflow(
        self,
        run_id: int,
        code_requirements: str | None = None,
        *,
        validation_policy: ValidationPolicy | None = None,
        sandbox_options: SandboxValidationOptions | None = None,
        validation_requirements: str | None = None,
        workflow_timeout_seconds: int | None = None,
        compute_target: ComputeTarget = ComputeTarget.CPU,
    ) -> LiteratureWaitInterrupt:
        """启动当前流程。"""
        run = await self.run_service.get_run(run_id)

        if run.status not in (
            LiteratureRunStatus.PENDING,
            LiteratureRunStatus.QUEUED,
            LiteratureRunStatus.RUNNING,
        ):
            raise LiteratureRunStateError(
                run_id,
                "start literature workflow",
            )

        if (
            validation_policy is None
            and sandbox_options is None
            and validation_requirements is None
            and workflow_timeout_seconds is None
            and compute_target is ComputeTarget.CPU
        ):
            return await self.workflow_service.start_literature_workflow(
                run_id,
                code_requirements,
            )

        return await self.workflow_service.start_literature_workflow(
            run_id,
            code_requirements,
            validation_policy=validation_policy,
            sandbox_options=sandbox_options,
            validation_requirements=validation_requirements,
            workflow_timeout_seconds=workflow_timeout_seconds,
            compute_target=compute_target,
        )

    async def resume_after_literature_completion(
        self,
        run_id: int,
    ) -> PaperSelectionInterrupt:
        """恢复暂停的流程。"""
        run = await self.run_service.get_run(run_id)

        if run.status is not LiteratureRunStatus.COMPLETED:
            raise LiteratureRunStateError(
                run_id,
                "resume literature workflow",
            )

        return await self.workflow_service.resume_literature_workflow(run_id)

    async def start_paper_selection(
        self,
        run_id: int,
        code_requirements: str | None = None,
        *,
        validation_policy: ValidationPolicy | None = None,
        sandbox_options: SandboxValidationOptions | None = None,
        validation_requirements: str | None = None,
        workflow_timeout_seconds: int | None = None,
        compute_target: ComputeTarget = ComputeTarget.CPU,
    ) -> PaperSelectionInterrupt:
        """启动当前流程。"""
        run = await self.run_service.get_run(run_id)

        if run.status is not LiteratureRunStatus.COMPLETED:
            raise LiteratureRunStateError(run_id, "start paper selection")

        if (
            validation_policy is None
            and sandbox_options is None
            and validation_requirements is None
            and workflow_timeout_seconds is None
            and compute_target is ComputeTarget.CPU
        ):
            return await self.workflow_service.start_paper_selection(
                run_id,
                code_requirements,
            )

        return await self.workflow_service.start_paper_selection(
            run_id,
            code_requirements,
            validation_policy=validation_policy,
            sandbox_options=sandbox_options,
            validation_requirements=validation_requirements,
            workflow_timeout_seconds=workflow_timeout_seconds,
            compute_target=compute_target,
        )

    async def confirm_paper_selection(
        self,
        run_id: int,
        request: PaperSelectionRequest,
    ) -> PaperSelection:
        """确认用户选择，并从 checkpoint 恢复下游流程。"""
        selection = await self.selection_service.confirm_selection(
            run_id,
            request,
        )

        await self.workflow_service.resume_paper_selection(
            run_id,
            request,
        )

        return selection
