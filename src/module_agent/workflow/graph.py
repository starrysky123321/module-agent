import inspect
from collections.abc import Callable
from time import perf_counter
from typing import Any, Literal

from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.run import CodeRunService
from module_agent.code.domain.jobs import CodeJobQueue, ComputeTarget
from module_agent.code.domain.run import CodeRunStatus
from module_agent.literature.application.dispatch import (
    LiteratureRunDispatcher,
)
from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationPolicy,
    ValidationRequest,
)

from langgraph.types import interrupt
from langgraph.errors import GraphInterrupt
from langchain_core.runnables import RunnableLambda

from module_agent.workflow.domain import (
    LiteratureCompletionSignal,
    LiteratureWaitInterrupt,
    CodeCompletionSignal,
    CodeWaitInterrupt,
    ModuleGraphState,
    PaperSelectionInterrupt,
    PaperSelectionRequest,
    SupervisorStep,
    WorkflowStatus,
)
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from module_agent.code.domain.request import CodeAgentRequest
from module_agent.code.domain.artifact import CodeArtifact
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecision,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.supervision.application.failure_classifier import (
    WorkflowFailureClassifier,
)
from uuid import UUID
from module_agent.workflow.lifecycle import WorkflowControlStatus
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.workflow.observation import (
    WorkflowNodeExecution,
    WorkflowNodeExecutionRecorder,
    WorkflowNodeExecutionStatus,
    summarize_workflow_state,
    workflow_node_attempt,
)
from module_agent.shared.logging import logger


SupervisorRoute = Literal[
    "literature_dispatch",
    "literature_wait",
    "paper_selection",
    "code",
    "code_wait",
    "validation",
    "finish",
]



class ModuleBuildWorkflow:
    """封装 ModuleBuildWorkflow 相关的数据和行为。"""
    def __init__(
        self,
        literature_dispatcher: LiteratureRunDispatcher,
        code_agent: CodeAgent,
        validation_agent: ValidationAgent,
        code_input_loader: SelectedPaperCodeInputLoader,
        supervisor_agent: SupervisorAgent | None = None,
        checkpointer: Any | None = None,
        failure_classifier: WorkflowFailureClassifier | None = None,
        code_run_service: CodeRunService | None = None,
        validation_run_service: ValidationRunService | None = None,
        lifecycle_service: ModuleWorkflowLifecycleService | None = None,
        node_execution_recorder: (
            WorkflowNodeExecutionRecorder | None
        ) = None,
        code_job_queue: CodeJobQueue | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.literature_dispatcher = literature_dispatcher
        self.code_agent = code_agent
        self.validation_agent = validation_agent
        self.supervisor_agent = supervisor_agent or SupervisorAgent()
        self.checkpointer = checkpointer
        self.code_input_loader = code_input_loader
        self.failure_classifier = (
            failure_classifier or WorkflowFailureClassifier()
        )
        self.code_run_service = code_run_service
        self.validation_run_service = validation_run_service
        self.lifecycle_service = lifecycle_service
        self.node_execution_recorder = node_execution_recorder
        self.code_job_queue = code_job_queue



    def build(self) -> CompiledStateGraph:
        """创建并编译 Module Agent 的 LangGraph。"""
        builder = StateGraph(ModuleGraphState)
        
        if self.checkpointer is None:
            raise ValueError("checkpointer must be provided")
        
        builder.add_node(
            "literature_wait",
            self._instrument_node(
                "literature_wait",
                self._literature_wait_node,
            ),
        )
        builder.add_node(
            "paper_selection",
            self._instrument_node(
                "paper_selection",
                self._paper_selection_node,
            ),
        )
        builder.add_node(
            "code",
            self._instrument_node("code", self._code_node),
        )
        builder.add_node(
            "code_wait",
            self._instrument_node("code_wait", self._code_wait_node),
        )
        builder.add_node(
            "validation",
            self._instrument_node(
                "validation",
                self._validation_node,
            ),
        )
        builder.add_node(
            "supervisor",
            self._instrument_node(
                "supervisor",
                self._supervisor_node,
            ),
        )
        
        builder.add_node(
            "literature_dispatch",
            self._instrument_node(
                "literature_dispatch",
                self._literature_dispatch_node,
            ),
        )
                
        builder.add_edge(START, "supervisor")

        builder.add_conditional_edges(
            "supervisor",
            self._route_supervisor,
            {
                "literature_dispatch": "literature_dispatch",
                "literature_wait": "literature_wait",
                "paper_selection": "paper_selection",
                "code": "code",
                "code_wait": "code_wait",
                "validation": "validation",
                "finish": END,
            },
        )

        builder.add_edge("literature_dispatch", "supervisor")
        builder.add_edge("literature_wait", "supervisor")
        builder.add_edge("paper_selection", "supervisor")
        builder.add_edge("code", "supervisor")
        builder.add_edge("code_wait", "supervisor")
        builder.add_edge("validation", "supervisor")
        
        return builder.compile(checkpointer=self.checkpointer)

    def _instrument_node(
        self,
        name: str,
        function: Callable[[ModuleGraphState], Any],
    ) -> RunnableLambda:
        async def observed(state: ModuleGraphState) -> dict[str, Any]:
            started = perf_counter()
            try:
                result = function(state)
                if inspect.isawaitable(result):
                    result = await result
            except GraphInterrupt:
                await self._record_node_execution(
                    name=name,
                    state=state,
                    output=None,
                    status=WorkflowNodeExecutionStatus.INTERRUPTED,
                    duration_ms=(perf_counter() - started) * 1000,
                )
                raise
            except Exception as exc:
                await self._record_node_execution(
                    name=name,
                    state=state,
                    output=None,
                    status=WorkflowNodeExecutionStatus.FAILED,
                    duration_ms=(perf_counter() - started) * 1000,
                    error=(str(exc).strip() or type(exc).__name__)[:1000],
                )
                raise

            if not isinstance(result, dict):
                raise TypeError(f"Workflow node {name} returned a non-dict")
            await self._record_node_execution(
                name=name,
                state=state,
                output=result,
                status=WorkflowNodeExecutionStatus.COMPLETED,
                duration_ms=(perf_counter() - started) * 1000,
            )
            return result

        return RunnableLambda(observed, name=name)

    async def _record_node_execution(
        self,
        *,
        name: str,
        state: ModuleGraphState,
        output: dict[str, Any] | None,
        status: WorkflowNodeExecutionStatus,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        if self.node_execution_recorder is None:
            return
        literature_run_id = state.get("literature_run_id")
        trace_id = self._optional_trace_id(state)
        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
            or trace_id is None
        ):
            return
        try:
            await self.node_execution_recorder.record(
                WorkflowNodeExecution(
                    literature_run_id=literature_run_id,
                    trace_id=trace_id,
                    node=name,
                    attempt=workflow_node_attempt(name, state, output),
                    status=status,
                    duration_ms=duration_ms,
                    input_summary=summarize_workflow_state(state),
                    output_summary=summarize_workflow_state(output or {}),
                    error=error,
                )
            )
        except Exception:
            logger.exception(
                "workflow node observation persistence failed | node={}",
                name,
            )

    def _paper_selection_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        literature_run_id = state.get("literature_run_id")
        if not literature_run_id or type(literature_run_id) != int or literature_run_id <= 0:
            raise ValueError("literature_run_id must be a positive integer")
        
        interrupt_payload = PaperSelectionInterrupt(
            literature_run_id=literature_run_id,
        ).model_dump(mode="json")
        
        resume_value = interrupt(interrupt_payload)
        
        selection = PaperSelectionRequest.model_validate(resume_value)
        
        return {
            "selected_paper_ids": selection.selected_paper_ids,
            "code_requirements": (
                selection.code_requirements
                if selection.code_requirements is not None
                else state.get("code_requirements")
            ),
            "status": WorkflowStatus.PREPARING_CODE.value,
            "next_step": SupervisorStep.CODE.value,
        }

    def _literature_wait_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        literature_run_id = state.get("literature_run_id")

        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        interrupt_payload = LiteratureWaitInterrupt(
            literature_run_id=literature_run_id,
        ).model_dump(mode="json")

        resume_value = interrupt(interrupt_payload)
        signal = LiteratureCompletionSignal.model_validate(resume_value)

        if signal.literature_run_id != literature_run_id:
            raise ValueError(
                "Literature completion signal does not match workflow"
            )

        return {
            "status": WorkflowStatus.WAITING_FOR_PAPER_SELECTION.value,
            "next_step": SupervisorStep.PAPER_SELECTION.value,
        }

    
    async def _literature_dispatch_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        literature_run_id = state.get("literature_run_id")

        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
        ):
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        
        attempts, current_attempt = self._record_attempt(
            state,
            SupervisorStep.LITERATURE,
        )

        control_result = await self._control_result(
            literature_run_id,
            SupervisorStep.LITERATURE,
            attempts,
            current_attempt,
        )
        if control_result is not None:
            return control_result

        try:
            trace_id = self._optional_trace_id(state)
            if trace_id is None:
                message_id = await self.literature_dispatcher.dispatch(
                    literature_run_id,
                    resume_workflow=True,
                )
            else:
                message_id = await self.literature_dispatcher.dispatch(
                    literature_run_id,
                    resume_workflow=True,
                    trace_id=trace_id,
                )
        except Exception as exc:
            return self._failure_result(
                step=SupervisorStep.LITERATURE,
                exc=exc,
                attempts=attempts,
                current_attempt=current_attempt,
            )

        return {
            "literature_message_id": message_id,
            "attempts": attempts,
            "status": WorkflowStatus.SEARCHING_LITERATURE.value,
            "next_step": SupervisorStep.LITERATURE.value,
        }



    async def _code_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        literature_run_id = state.get("literature_run_id")
        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
        ):
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        selected_paper_ids = state.get("selected_paper_ids")
        if not selected_paper_ids:
            raise ValueError("selected_paper_ids cannot be empty")
        
        attempts, current_attempt = self._record_attempt(
            state,
            SupervisorStep.CODE,
        )

        control_result = await self._control_result(
            literature_run_id,
            SupervisorStep.CODE,
            attempts,
            current_attempt,
        )
        if control_result is not None:
            return control_result

        try:
            papers = await self.code_input_loader.load(
                literature_run_id,
                selected_paper_ids,
            )

            request = CodeAgentRequest(
                literature_run_id=literature_run_id,
                papers=papers,
                code_requirements=state.get("code_requirements"),
            )

            if self.code_job_queue is not None:
                trace_id = self._trace_id(state)
                compute_target = ComputeTarget(
                    state.get("compute_target", ComputeTarget.CPU.value)
                )
                message_id = await self.code_job_queue.enqueue(
                    request,
                    attempt=current_attempt,
                    trace_id=trace_id,
                    compute_target=compute_target,
                )
                return {
                    "selected_papers": [
                        paper.model_dump(mode="json") for paper in papers
                    ],
                    "code_message_id": message_id,
                    "attempts": attempts,
                    "status": WorkflowStatus.WAITING_FOR_CODE.value,
                    "next_step": SupervisorStep.CODE.value,
                }

            code_run_id = None
            if self.code_run_service is None:
                artifacts = await self.code_agent.run(request)
            else:
                trace_id = self._trace_id(state)
                code_run = await self.code_run_service.execute(
                    request,
                    attempt=current_attempt,
                    trace_id=trace_id,
                )
                code_run_id = code_run.id
                artifacts = code_run.artifacts
        except Exception as exc:
            return self._failure_result(
                step=SupervisorStep.CODE,
                exc=exc,
                attempts=attempts,
                current_attempt=current_attempt,
            )

        control_result = await self._control_result(
            literature_run_id,
            SupervisorStep.CODE,
            attempts,
            current_attempt,
        )
        if control_result is not None:
            control_result.update(
                {
                    "selected_papers": [
                        paper.model_dump(mode="json") for paper in papers
                    ],
                    "code_artifacts": [
                        artifact.model_dump(mode="json")
                        for artifact in artifacts
                    ],
                }
            )
            if code_run_id is not None:
                control_result["code_run_id"] = code_run_id
            return control_result

        result: dict[str, Any] = {
            "selected_papers": [
                paper.model_dump(mode="json")
                for paper in papers
            ],
            "code_artifacts": [
                artifact.model_dump(mode="json")
                for artifact in artifacts
            ],
            "status": WorkflowStatus.CODE_READY.value,
            "next_step": SupervisorStep.VALIDATION.value,
            "attempts": attempts,
        }
        if code_run_id is not None:
            result["code_run_id"] = code_run_id
        return result

    async def _code_wait_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        """Pause until a Code Worker reports a persisted completed run."""
        literature_run_id = state.get("literature_run_id")
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError("literature_run_id must be a positive integer")
        if self.code_run_service is None:
            raise RuntimeError("CodeRunService is required for queued code work")

        resume_value = interrupt(
            CodeWaitInterrupt(
                literature_run_id=literature_run_id
            ).model_dump(mode="json")
        )
        signal = CodeCompletionSignal.model_validate(resume_value)
        if signal.literature_run_id != literature_run_id:
            raise ValueError("Code completion signal does not match workflow")

        code_run = await self.code_run_service.get_run(signal.code_run_id)
        if code_run.literature_run_id != literature_run_id:
            raise ValueError("CodeRun belongs to another workflow")
        if code_run.status is CodeRunStatus.FAILED:
            attempts = dict(state.get("attempts") or {})
            current_attempt = max(
                int(attempts.get(SupervisorStep.CODE.value, 1)), 1
            )
            return self._failure_result(
                step=SupervisorStep.CODE,
                exc=RuntimeError(code_run.error or "CodeRun failed"),
                attempts=attempts,
                current_attempt=current_attempt,
            )
        if code_run.status is not CodeRunStatus.COMPLETED:
            raise ValueError("CodeRun is not completed")
        return {
            "code_run_id": signal.code_run_id,
            "code_artifacts": [
                artifact.model_dump(mode="json")
                for artifact in code_run.artifacts
            ],
            "status": WorkflowStatus.CODE_READY.value,
            "next_step": SupervisorStep.VALIDATION.value,
        }

    async def _validation_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        literature_run_id = state.get("literature_run_id")
        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
        ):
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        raw_artifacts = state.get("code_artifacts")
        if not raw_artifacts:
            raise ValueError("code_artifacts cannot be empty")
        
        attempts, current_attempt = self._record_attempt(
            state,
            SupervisorStep.VALIDATION,
        )

        control_result = await self._control_result(
            literature_run_id,
            SupervisorStep.VALIDATION,
            attempts,
            current_attempt,
        )
        if control_result is not None:
            return control_result

        try:
            request = ValidationRequest(
                literature_run_id=literature_run_id,
                artifacts=[
                    CodeArtifact.model_validate(artifact)
                    for artifact in raw_artifacts
                ],
                policy=ValidationPolicy.model_validate(
                    state.get("validation_policy", {})
                ),
                sandbox_options=(
                    SandboxValidationOptions.model_validate(
                        state.get("sandbox_options", {})
                    )
                    if state.get("sandbox_options") is not None
                    else None
                ),
                user_requirements=state.get("validation_requirements"),
            )

            validation_run_id = None
            if self.validation_run_service is None:
                reports = await self.validation_agent.run(request)
            else:
                trace_id = self._trace_id(state)
                validation_run = (
                    await self.validation_run_service.execute(
                        request,
                        attempt=current_attempt,
                        trace_id=trace_id,
                    )
                )
                validation_run_id = validation_run.id
                reports = validation_run.reports
        except Exception as exc:
            return self._failure_result(
                step=SupervisorStep.VALIDATION,
                exc=exc,
                attempts=attempts,
                current_attempt=current_attempt,
            )

        control_result = await self._control_result(
            literature_run_id,
            SupervisorStep.VALIDATION,
            attempts,
            current_attempt,
        )
        if control_result is not None:
            control_result["validation_reports"] = [
                report.model_dump(mode="json") for report in reports
            ]
            if validation_run_id is not None:
                control_result["validation_run_id"] = validation_run_id
            return control_result
        result: dict[str, Any] = {
            "validation_reports": [
                report.model_dump(mode="json")
                for report in reports
            ],
            "status": WorkflowStatus.COMPLETED.value,
            "next_step": SupervisorStep.FINISH.value,
            "attempts": attempts,
        }
        if validation_run_id is not None:
            result["validation_run_id"] = validation_run_id
        return result


    
    async def _supervisor_node(
        self,
        state: ModuleGraphState,
    ) -> dict[str, Any]:
        decision = await self.supervisor_agent.run(state)

        result: dict[str, Any] = {
            "supervisor_decision": decision.model_dump(mode="json"),
            "status": decision.status.value,
            "next_step": decision.next_step.value,
        }

        if decision.action is SupervisorAction.RETRY:
            result["failure"] = None

        return result


    def _route_supervisor(
        self,
        state: ModuleGraphState,
    ) -> SupervisorRoute:
        raw_decision = state.get("supervisor_decision")

        if raw_decision is None:
            raise ValueError("Workflow has no supervisor decision")

        decision = SupervisorDecision.model_validate(raw_decision)

        if decision.action in {
            SupervisorAction.FINISH,
            SupervisorAction.FAIL,
            SupervisorAction.CANCEL,
        }:
            return "finish"

        if (
            decision.action is SupervisorAction.WAIT
            and decision.next_step is SupervisorStep.LITERATURE
        ):
            return "literature_wait"

        if (
            decision.action is SupervisorAction.WAIT
            and decision.next_step is SupervisorStep.CODE
        ):
            return "code_wait"

        routes: dict[SupervisorStep, SupervisorRoute] = {
            SupervisorStep.LITERATURE: "literature_dispatch",
            SupervisorStep.PAPER_SELECTION: "paper_selection",
            SupervisorStep.CODE: "code",
            SupervisorStep.VALIDATION: "validation",
        }


        route = routes.get(decision.next_step)

        if route is None:
            raise ValueError(
                f"Unsupported supervisor step: {decision.next_step}"
            )

        return route

    @staticmethod
    def _record_attempt(
        state: ModuleGraphState,
        step: SupervisorStep,
    ) -> tuple[dict[str, int], int]:
        attempts = dict(state.get("attempts") or {})
        current_attempt = attempts.get(step.value, 0) + 1
        attempts[step.value] = current_attempt

        return attempts, current_attempt

    @staticmethod
    def _trace_id(state: ModuleGraphState) -> UUID:
        raw_trace_id = state.get("trace_id")
        if not isinstance(raw_trace_id, str):
            raise ValueError("Workflow trace_id is missing")
        try:
            return UUID(raw_trace_id)
        except ValueError as exc:
            raise ValueError("Workflow trace_id is invalid") from exc

    @staticmethod
    def _optional_trace_id(state: ModuleGraphState) -> UUID | None:
        raw_trace_id = state.get("trace_id")
        if raw_trace_id is None:
            return None
        if not isinstance(raw_trace_id, str):
            raise ValueError("Workflow trace_id is invalid")
        try:
            return UUID(raw_trace_id)
        except ValueError as exc:
            raise ValueError("Workflow trace_id is invalid") from exc

    async def _control_result(
        self,
        literature_run_id: int,
        step: SupervisorStep,
        attempts: dict[str, int],
        current_attempt: int,
    ) -> dict[str, Any] | None:
        if self.lifecycle_service is None:
            return None
        control = await self.lifecycle_service.check_control(
            literature_run_id
        )
        if control is WorkflowControlStatus.ACTIVE:
            return None
        if control is WorkflowControlStatus.CANCELLED:
            return {
                "attempts": attempts,
                "status": WorkflowStatus.CANCELLED.value,
                "next_step": SupervisorStep.FINISH.value,
            }

        failure = WorkflowFailure(
            step=step,
            category=WorkflowFailureCategory.TIMEOUT,
            message="Workflow deadline exceeded",
            retryable=False,
            attempt=current_attempt,
            error_type="WorkflowTimeoutError",
        )
        return {
            "attempts": attempts,
            "failure": failure.model_dump(mode="json"),
            "status": WorkflowStatus.FAILED.value,
            "next_step": SupervisorStep.FINISH.value,
        }


    
    def _failure_result(
        self,
        *,
        step: SupervisorStep,
        exc: Exception,
        attempts: dict[str, int],
        current_attempt: int,
    ) -> dict[str, Any]:
        failure = self.failure_classifier.classify(
            step,
            exc,
            attempt=current_attempt,
        )

        return {
            "attempts": attempts,
            "failure": failure.model_dump(mode="json"),
            "status": WorkflowStatus.FAILED.value,
        }
