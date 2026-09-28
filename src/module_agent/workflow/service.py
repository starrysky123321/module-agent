from langgraph.graph.state import CompiledStateGraph
from module_agent.workflow.domain import WorkflowStatus, SupervisorStep
from module_agent.workflow.domain import CodeCompletionSignal
from module_agent.code.domain.jobs import ComputeTarget
from module_agent.workflow.domain import PaperSelectionInterrupt, PaperSelectionRequest
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from module_agent.workflow.domain import ModuleGraphState
from module_agent.workflow.domain import LiteratureWaitInterrupt
from typing import Any, cast
from uuid import UUID, uuid4
from module_agent.workflow.domain import LiteratureCompletionSignal

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.validation.domain.report import ValidationReport
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationPolicy,
)
from module_agent.shared.exceptions import (
    WorkflowAlreadyProgressedError,
    WorkflowNotWaitingForSelectionError,
    WorkflowNotWaitingForLiteratureError,
    WorkflowResultNotReadyError,
)
from module_agent.workflow.result import ModuleBuildResult
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunStatus,
    WorkflowControlStatus,
)
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.shared.exceptions import WorkflowControlError
from module_agent.shared.context import observability_context
from module_agent.shared.logging import logger
from module_agent.workflow.state import (
    apply_timeout_failure,
    build_initial_state,
    failure_message,
    lifecycle_status_for_graph,
    resumable_wait_status,
    validate_run_id,
    workflow_config,
)



class ModuleWorkflowService:
    """封装相关应用用例。"""
    def __init__(
        self,
        graph: CompiledStateGraph,
        lifecycle_service: ModuleWorkflowLifecycleService | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.graph = graph
        self.lifecycle_service = lifecycle_service
        
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
        validate_run_id(run_id)
        
        
        config = workflow_config(run_id)
        
        snapshot = await self.graph.aget_state(config)
        
        if snapshot.interrupts:
            return PaperSelectionInterrupt.model_validate(
                snapshot.interrupts[0].value
            )

        if snapshot.values:
            raise WorkflowAlreadyProgressedError(run_id)
        
        
        trace_id = await self._start_lifecycle(
            run_id,
            workflow_timeout_seconds,
        )
        result = await self._invoke_graph(
            run_id,
            trace_id,
            build_initial_state(
                run_id=run_id,
                trace_id=trace_id,
                code_requirements=code_requirements,
                validation_policy=validation_policy,
                sandbox_options=sandbox_options,
                validation_requirements=validation_requirements,
                compute_target=compute_target,
                status=WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
                next_step=SupervisorStep.PAPER_SELECTION,
            ),
            config,
        )
        
        interrupts = result.get("__interrupt__", ())
        
        if not interrupts:
            raise RuntimeError("Workflow did not pause for paper selection")

        await self._set_lifecycle_status(
            run_id,
            ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
        )

        return PaperSelectionInterrupt.model_validate(
            interrupts[0].value
        )
    
    async def resume_paper_selection(self, run_id: int, request: PaperSelectionRequest) -> ModuleGraphState:
        """恢复暂停的流程。"""
        validate_run_id(run_id)
        
        trace_id = await self._ensure_active(
            run_id,
            "resume paper selection",
        )
        config = workflow_config(run_id)
        
        snapshot = await self.graph.aget_state(config)

        if not snapshot.interrupts:
            raise WorkflowNotWaitingForSelectionError(run_id)
                
        result = await self._invoke_graph(
            run_id,
            trace_id,
            Command(resume=request.model_dump(mode="json")),
            config,
        )
        
        state = cast(ModuleGraphState, cast(object, result))
        await self._sync_lifecycle(run_id, state)
        return state

    async def resume_code_workflow(
        self,
        run_id: int,
        code_run_id: int,
    ) -> ModuleGraphState:
        """Resume a workflow paused while an independent Code Worker ran."""
        validate_run_id(run_id)
        if type(code_run_id) is not int or code_run_id <= 0:
            raise ValueError("code_run_id must be a positive integer")
        trace_id = await self._ensure_active(run_id, "resume code workflow")
        config = workflow_config(run_id)
        snapshot = await self.graph.aget_state(config)
        if (
            not snapshot.interrupts
            or snapshot.values.get("status")
            != WorkflowStatus.WAITING_FOR_CODE.value
        ):
            raise WorkflowControlError(
                run_id, "workflow is not waiting for code completion"
            )
        signal = CodeCompletionSignal(
            literature_run_id=run_id,
            code_run_id=code_run_id,
        )
        result = await self._invoke_graph(
            run_id,
            trace_id,
            Command(resume=signal.model_dump(mode="json")),
            config,
        )
        state = cast(ModuleGraphState, cast(object, result))
        await self._sync_lifecycle(run_id, state)
        return state

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
        validate_run_id(run_id)

        config = workflow_config(run_id)

        snapshot = await self.graph.aget_state(config)

        if snapshot.interrupts:
            if (
                snapshot.values.get("status")
                == WorkflowStatus.SEARCHING_LITERATURE.value
            ):
                return LiteratureWaitInterrupt.model_validate(
                    snapshot.interrupts[0].value
                )

            raise WorkflowAlreadyProgressedError(run_id)

        if snapshot.values:
            raise WorkflowAlreadyProgressedError(run_id)

        trace_id = await self._start_lifecycle(
            run_id,
            workflow_timeout_seconds,
        )
        result = await self._invoke_graph(
            run_id,
            trace_id,
            build_initial_state(
                run_id=run_id,
                trace_id=trace_id,
                code_requirements=code_requirements,
                validation_policy=validation_policy,
                sandbox_options=sandbox_options,
                validation_requirements=validation_requirements,
                compute_target=compute_target,
                status=WorkflowStatus.SEARCHING_LITERATURE,
                next_step=SupervisorStep.LITERATURE,
            ),
            config,
        )

        interrupts = result.get("__interrupt__", ())

        if not interrupts:
            raise RuntimeError(
                "Workflow did not pause for literature completion"
            )

        await self._set_lifecycle_status(
            run_id,
            ModuleWorkflowRunStatus.WAITING_FOR_LITERATURE,
        )

        return LiteratureWaitInterrupt.model_validate(
            interrupts[0].value
        )


    async def resume_literature_workflow(
        self,
        run_id: int,
    ) -> PaperSelectionInterrupt:
        """恢复暂停的流程。"""
        validate_run_id(run_id)
        
        trace_id = await self._ensure_active(
            run_id,
            "resume literature workflow",
        )
        config = workflow_config(run_id)
        
        snapshot = await self.graph.aget_state(config)

        if (
            snapshot.interrupts
            and snapshot.values.get("status")
            == WorkflowStatus.WAITING_FOR_PAPER_SELECTION.value
        ):
            return PaperSelectionInterrupt.model_validate(
                snapshot.interrupts[0].value
            )

        if (
            not snapshot.interrupts
            or snapshot.values.get("status")
            != WorkflowStatus.SEARCHING_LITERATURE.value
        ):
            raise WorkflowNotWaitingForLiteratureError(run_id)

        signal = LiteratureCompletionSignal(
            literature_run_id=run_id,
        )

        result = await self._invoke_graph(
            run_id,
            trace_id,
            Command(resume=signal.model_dump(mode="json")),
            config,
        )
        
        interrupts = result.get("__interrupt__", ())
        if not interrupts:
            raise RuntimeError(
                "Workflow did not pause for paper selection"
            )

        await self._set_lifecycle_status(
            run_id,
            ModuleWorkflowRunStatus.WAITING_FOR_SELECTION,
        )

        return PaperSelectionInterrupt.model_validate(
            interrupts[0].value
        )
    
    async def get_code_artifacts(
        self,
        run_id: int,
    ) -> list[CodeArtifact]:
        """获取对应记录。"""
        validate_run_id(run_id)

        config = workflow_config(run_id)

        snapshot = await self.graph.aget_state(config)

        raw_artifacts = snapshot.values.get("code_artifacts", [])

        return [
            CodeArtifact.model_validate(artifact)
            for artifact in raw_artifacts
        ]

    async def get_validation_reports(
        self,
        run_id: int,
    ) -> list[ValidationReport]:
        """获取对应记录。"""
        validate_run_id(run_id)

        config = workflow_config(run_id)
        snapshot = await self.graph.aget_state(config)
        raw_reports = snapshot.values.get("validation_reports", [])
        return [
            ValidationReport.model_validate(report)
            for report in raw_reports
        ]


    async def get_result(
        self,
        run_id: int,
    ) -> ModuleBuildResult:
        """获取对应记录。"""
        validate_run_id(run_id)

        config = workflow_config(run_id)

        snapshot = await self.graph.aget_state(config)
        values = dict(snapshot.values)
        raw_status = values.get("status")

        terminal_statuses = {
            WorkflowStatus.COMPLETED.value,
            WorkflowStatus.FAILED.value,
            WorkflowStatus.CANCELLED.value,
        }

        lifecycle = None
        if self.lifecycle_service is not None:
            await self.lifecycle_service.check_control(run_id)
            lifecycle = await self.lifecycle_service.get(run_id)
            if lifecycle.status is ModuleWorkflowRunStatus.CANCELLED:
                values["status"] = WorkflowStatus.CANCELLED.value
                values["failure"] = None
                raw_status = WorkflowStatus.CANCELLED.value
            elif lifecycle.status is ModuleWorkflowRunStatus.TIMED_OUT:
                apply_timeout_failure(values)
                raw_status = WorkflowStatus.FAILED.value

        if raw_status not in terminal_statuses:
            raise WorkflowResultNotReadyError(
                run_id,
                raw_status if isinstance(raw_status, str) else None,
            )

        reports = [
            ValidationReport.model_validate(report)
            for report in values.get("validation_reports", [])
        ]

        values["validation_reports"] = reports
        values["warnings"] = list(
            dict.fromkeys(
                warning
                for report in reports
                for warning in report.warnings
            )
        )

        return ModuleBuildResult.model_validate(values)

    async def cancel(self, run_id: int) -> ModuleWorkflowRun:
        """取消当前流程。"""
        if self.lifecycle_service is None:
            raise RuntimeError("Workflow lifecycle service is not configured")
        run = await self.lifecycle_service.cancel(run_id)
        config = workflow_config(run_id)
        with observability_context(
            trace_id=run.trace_id,
            workflow_id=run_id,
        ):
            snapshot = await self.graph.aget_state(config)
            if snapshot.values:
                await self.graph.aupdate_state(
                    config,
                    {
                        "status": WorkflowStatus.CANCELLED.value,
                        "next_step": SupervisorStep.FINISH.value,
                        "failure": None,
                    },
                )
            logger.info("workflow cancelled")
        return run

    async def get_lifecycle(self, run_id: int) -> ModuleWorkflowRun:
        """获取对应记录。"""
        if self.lifecycle_service is None:
            raise RuntimeError("Workflow lifecycle service is not configured")
        await self.lifecycle_service.check_control(run_id)
        return await self.lifecycle_service.get(run_id)

    async def resume_timed_out(
        self,
        run_id: int,
        *,
        timeout_seconds: int | None = None,
    ) -> ModuleWorkflowRun:
        """恢复暂停的流程。"""
        if self.lifecycle_service is None:
            raise RuntimeError("Workflow lifecycle service is not configured")
        lifecycle = await self.lifecycle_service.get(run_id)
        if lifecycle.status is not ModuleWorkflowRunStatus.TIMED_OUT:
            raise WorkflowControlError(
                run_id,
                "only a timed-out workflow can be resumed",
            )
        config = workflow_config(run_id)
        snapshot = await self.graph.aget_state(config)
        raw_status = snapshot.values.get("status")
        target = resumable_wait_status(raw_status)
        if target is None or not snapshot.interrupts:
            raise WorkflowControlError(
                run_id,
                "timed-out workflow is not paused at a resumable wait point",
            )
        resumed = await self.lifecycle_service.resume_timed_out(
            run_id,
            status=target,
            timeout_seconds=timeout_seconds,
        )
        with observability_context(
            trace_id=resumed.trace_id,
            workflow_id=run_id,
        ):
            logger.info(
                "timed-out workflow resumed | wait_status={} deadline={}",
                target.value,
                resumed.deadline_at.isoformat(),
            )
        return resumed

    async def _start_lifecycle(
        self,
        run_id: int,
        timeout_seconds: int | None,
    ) -> UUID:
        if self.lifecycle_service is None:
            return uuid4()
        run = await self.lifecycle_service.start(
            run_id,
            timeout_seconds=timeout_seconds,
        )
        return run.trace_id

    async def _set_lifecycle_status(
        self,
        run_id: int,
        status: ModuleWorkflowRunStatus,
    ) -> None:
        if self.lifecycle_service is not None:
            await self.lifecycle_service.set_status(run_id, status)

    async def _ensure_active(
        self,
        run_id: int,
        action: str,
    ) -> UUID | None:
        if self.lifecycle_service is None:
            return None
        control = await self.lifecycle_service.check_control(run_id)
        if control is not WorkflowControlStatus.ACTIVE:
            raise WorkflowControlError(
                run_id,
                f"cannot {action}: workflow is {control.value}",
            )
        return (await self.lifecycle_service.get(run_id)).trace_id

    async def _invoke_graph(
        self,
        run_id: int,
        trace_id: UUID | None,
        input_value: Any,
        config: RunnableConfig,
    ) -> dict[str, Any]:
        with observability_context(
            trace_id=trace_id,
            workflow_id=run_id,
        ):
            try:
                return await self.graph.ainvoke(input_value, config)
            except Exception as exc:
                message = (str(exc).strip() or type(exc).__name__)[:1000]
                if self.lifecycle_service is not None:
                    await self.lifecycle_service.set_status(
                        run_id,
                        ModuleWorkflowRunStatus.FAILED,
                        error=message,
                    )
                logger.exception("workflow invocation failed")
                raise

    async def _sync_lifecycle(
        self,
        run_id: int,
        state: ModuleGraphState,
    ) -> None:
        if self.lifecycle_service is None:
            return
        lifecycle_status = lifecycle_status_for_graph(state.get("status"))
        if lifecycle_status is not None:
            await self.lifecycle_service.set_status(
                run_id,
                lifecycle_status,
                error=failure_message(state),
            )
