from collections.abc import Collection

from module_agent.supervision.domain import (
    WorkflowConfigurationError,
    WorkflowFailure,
    WorkflowFailureCategory,
    WorkflowStateValidationError,
)
from module_agent.workflow.domain import SupervisorStep


class WorkflowFailureClassifier:
    """封装 WorkflowFailureClassifier 相关的数据和行为。"""
    DEFAULT_RETRYABLE_STEPS = frozenset(
        {
            SupervisorStep.LITERATURE,
            SupervisorStep.VALIDATION,
        }
    )

    def __init__(
        self,
        *,
        max_attempts: int = 2,
        retryable_steps: Collection[SupervisorStep] | None = None,
    ) -> None:
        """初始化当前对象。"""
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")

        self.max_attempts = max_attempts
        self.retryable_steps = frozenset(
            retryable_steps
            if retryable_steps is not None
            else self.DEFAULT_RETRYABLE_STEPS
        )

        if SupervisorStep.FINISH in self.retryable_steps:
            raise ValueError("The finish step cannot be retried")

    def classify(
        self,
        step: SupervisorStep,
        exc: Exception,
        *,
        attempt: int = 1,
    ) -> WorkflowFailure:
        """对输入进行分类。"""
        if type(attempt) is not int or attempt < 1:
            raise ValueError("attempt must be at least 1")

        if isinstance(exc, WorkflowStateValidationError):
            category = WorkflowFailureCategory.INVALID_STATE
        elif isinstance(exc, WorkflowConfigurationError):
            category = WorkflowFailureCategory.CONFIGURATION
        elif isinstance(exc, TimeoutError):
            category = WorkflowFailureCategory.TIMEOUT
        elif isinstance(exc, ConnectionError):
            category = WorkflowFailureCategory.TRANSIENT_EXTERNAL
        else:
            category = WorkflowFailureCategory.INTERNAL

        potentially_retryable = category in {
            WorkflowFailureCategory.TIMEOUT,
            WorkflowFailureCategory.TRANSIENT_EXTERNAL,
        }

        retryable = (
            potentially_retryable
            and step in self.retryable_steps
            and attempt < self.max_attempts
        )

        message = str(exc).strip() or type(exc).__name__

        return WorkflowFailure(
            step=step,
            category=category,
            message=message[:1000],
            retryable=retryable,
            attempt=attempt,
            error_type=type(exc).__name__[:200],
        )
