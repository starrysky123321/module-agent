from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecision,
    WorkflowFailure,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)

class RuleBasedSupervisorPolicy:
    """定义业务决策策略。"""
    async def decide(
        self,
        state: ModuleGraphState,
        status: WorkflowStatus,
    ) -> SupervisorDecision:
        """根据当前状态生成决策。"""
        if status is WorkflowStatus.CREATED:
            return SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.LITERATURE,
                status=WorkflowStatus.SEARCHING_LITERATURE,
                reason="The workflow is ready to start literature search",
            )

        if status is WorkflowStatus.SEARCHING_LITERATURE:
            message_id = state.get("literature_message_id")

            if isinstance(message_id, str) and message_id.strip():
                return SupervisorDecision(
                    action=SupervisorAction.WAIT,
                    next_step=SupervisorStep.LITERATURE,
                    status=WorkflowStatus.SEARCHING_LITERATURE,
                    reason="Literature search has been dispatched",
                )

            return SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.LITERATURE,
                status=WorkflowStatus.SEARCHING_LITERATURE,
                reason="Literature search has not been dispatched",
            )

        if status is WorkflowStatus.WAITING_FOR_PAPER_SELECTION:
            return SupervisorDecision(
                action=SupervisorAction.WAIT,
                next_step=SupervisorStep.PAPER_SELECTION,
                status=WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
                reason="User paper selection is required",
            )

        if status is WorkflowStatus.PREPARING_CODE:
            return SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.CODE,
                status=WorkflowStatus.PREPARING_CODE,
                reason="Selected papers are ready for code preparation",
            )

        if status is WorkflowStatus.WAITING_FOR_CODE:
            return SupervisorDecision(
                action=SupervisorAction.WAIT,
                next_step=SupervisorStep.CODE,
                status=WorkflowStatus.WAITING_FOR_CODE,
                reason="Code work has been dispatched",
            )

        if status is WorkflowStatus.CODE_READY:
            return SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.VALIDATION,
                status=WorkflowStatus.VALIDATING,
                reason="Code artifacts are ready for validation",
            )

        if status is WorkflowStatus.VALIDATING:
            return SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.VALIDATION,
                status=WorkflowStatus.VALIDATING,
                reason="Validation has not produced reports yet",
            )

        if status is WorkflowStatus.COMPLETED:
            return SupervisorDecision(
                action=SupervisorAction.FINISH,
                next_step=SupervisorStep.FINISH,
                status=WorkflowStatus.COMPLETED,
                reason="All selected artifacts have validation reports",
            )

        if status is WorkflowStatus.CANCELLED:
            return SupervisorDecision(
                action=SupervisorAction.CANCEL,
                next_step=SupervisorStep.FINISH,
                status=WorkflowStatus.CANCELLED,
                reason="Workflow cancellation was requested",
            )

        if status is WorkflowStatus.FAILED:
            failure = WorkflowFailure.model_validate(
                state.get("failure")
            )

            retry_statuses = {
                SupervisorStep.LITERATURE: (
                    WorkflowStatus.SEARCHING_LITERATURE
                ),
                SupervisorStep.PAPER_SELECTION: (
                    WorkflowStatus.WAITING_FOR_PAPER_SELECTION
                ),
                SupervisorStep.CODE: WorkflowStatus.PREPARING_CODE,
                SupervisorStep.VALIDATION: WorkflowStatus.VALIDATING,
            }

            retry_status = retry_statuses.get(failure.step)

            if failure.retryable and retry_status is not None:
                return SupervisorDecision(
                    action=SupervisorAction.RETRY,
                    next_step=failure.step,
                    status=retry_status,
                    reason=(
                        f"Retrying {failure.step.value} after "
                        f"attempt {failure.attempt}: {failure.message}"
                    ),
                )

            return SupervisorDecision(
                action=SupervisorAction.FAIL,
                next_step=SupervisorStep.FINISH,
                status=WorkflowStatus.FAILED,
                reason=(
                    f"Workflow stopped at {failure.step.value}: "
                    f"{failure.message}"
                ),
            )

        raise ValueError(f"Unsupported workflow status: {status!r}")
