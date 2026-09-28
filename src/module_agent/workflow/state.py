"""Pure state construction and transition helpers for workflow services."""

from langchain_core.runnables import RunnableConfig

from module_agent.code.domain.jobs import ComputeTarget
from module_agent.supervision.domain import (
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationPolicy,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)
from module_agent.workflow.lifecycle import ModuleWorkflowRunStatus


def validate_run_id(run_id: int) -> None:
    """Reject bool and non-positive identifiers at the service boundary."""
    if type(run_id) is not int or run_id <= 0:
        raise ValueError("run_id must be a positive integer")


def workflow_config(run_id: int) -> RunnableConfig:
    """Return the stable LangGraph thread configuration for one run."""
    return RunnableConfig(
        configurable={"thread_id": f"literature-run:{run_id}"}
    )


def build_initial_state(
    *,
    run_id: int,
    trace_id: object,
    code_requirements: str | None,
    validation_policy: ValidationPolicy | None,
    sandbox_options: SandboxValidationOptions | None,
    validation_requirements: str | None,
    compute_target: ComputeTarget,
    status: WorkflowStatus,
    next_step: SupervisorStep,
) -> ModuleGraphState:
    """Serialize API models into the checkpoint-safe initial graph state."""
    return {
        "literature_run_id": run_id,
        "trace_id": str(trace_id),
        "code_requirements": code_requirements,
        "validation_policy": (
            validation_policy or ValidationPolicy()
        ).model_dump(mode="json"),
        "sandbox_options": (
            sandbox_options.model_dump(mode="json")
            if sandbox_options is not None
            else None
        ),
        "validation_requirements": validation_requirements,
        "compute_target": compute_target.value,
        "status": status.value,
        "next_step": next_step.value,
    }


def lifecycle_status_for_graph(
    raw_status: object,
) -> ModuleWorkflowRunStatus | None:
    """Map a graph status to its durable lifecycle status."""
    if not isinstance(raw_status, str):
        return None
    return {
        WorkflowStatus.WAITING_FOR_CODE.value: (
            ModuleWorkflowRunStatus.WAITING_FOR_CODE
        ),
        WorkflowStatus.COMPLETED.value: ModuleWorkflowRunStatus.COMPLETED,
        WorkflowStatus.FAILED.value: ModuleWorkflowRunStatus.FAILED,
        WorkflowStatus.CANCELLED.value: ModuleWorkflowRunStatus.CANCELLED,
    }.get(raw_status)


def resumable_wait_status(
    raw_status: object,
) -> ModuleWorkflowRunStatus | None:
    """Map a paused graph status to the lifecycle state used on resume."""
    if not isinstance(raw_status, str):
        return None
    return {
        WorkflowStatus.SEARCHING_LITERATURE.value: (
            ModuleWorkflowRunStatus.WAITING_FOR_LITERATURE
        ),
        WorkflowStatus.WAITING_FOR_PAPER_SELECTION.value: (
            ModuleWorkflowRunStatus.WAITING_FOR_SELECTION
        ),
        WorkflowStatus.WAITING_FOR_CODE.value: (
            ModuleWorkflowRunStatus.WAITING_FOR_CODE
        ),
    }.get(raw_status)


def failure_message(state: ModuleGraphState) -> str | None:
    """Extract a bounded lifecycle error from structured graph failure."""
    failure = state.get("failure")
    if not isinstance(failure, dict):
        return None
    message = failure.get("message")
    return message if isinstance(message, str) else None


def apply_timeout_failure(values: dict[str, object]) -> None:
    """Convert a lifecycle timeout into a terminal graph failure."""
    raw_step = values.get("next_step", SupervisorStep.FINISH.value)
    try:
        step = SupervisorStep(raw_step)
    except (TypeError, ValueError):
        step = SupervisorStep.FINISH
    raw_attempts = values.get("attempts")
    attempts = dict(raw_attempts) if isinstance(raw_attempts, dict) else {}
    raw_attempt = attempts.get(step.value, 0)
    attempt = max(raw_attempt if isinstance(raw_attempt, int) else 0, 1)
    attempts[step.value] = attempt
    failure = WorkflowFailure(
        step=step,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Workflow deadline exceeded",
        retryable=False,
        attempt=attempt,
        error_type="WorkflowTimeoutError",
    )
    values["attempts"] = attempts
    values["failure"] = failure.model_dump(mode="json")
    values["status"] = WorkflowStatus.FAILED.value
