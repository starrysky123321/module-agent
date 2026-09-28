import asyncio
from unittest.mock import AsyncMock

from module_agent.supervision.application.guarded_policy import (
    GuardedSupervisorPolicy,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorAction,
    SupervisorDecision,
    SupervisorDecisionPolicy,
    SupervisorFailureAdvice,
    SupervisorFailureAdvisor,
    SupervisorObservationSink,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)


def failed_state(*, retryable: bool) -> ModuleGraphState:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=retryable,
        attempt=2,
        error_type="TimeoutError",
    )
    return {
        "literature_run_id": 7,
        "status": WorkflowStatus.FAILED.value,
        "failure": failure.model_dump(mode="json"),
    }


def retry_decision() -> SupervisorDecision:
    return SupervisorDecision(
        action=SupervisorAction.RETRY,
        next_step=SupervisorStep.VALIDATION,
        status=WorkflowStatus.VALIDATING,
        reason="Retry validation",
    )


def fail_decision() -> SupervisorDecision:
    return SupervisorDecision(
        action=SupervisorAction.FAIL,
        next_step=SupervisorStep.FINISH,
        status=WorkflowStatus.FAILED,
        reason="Stop workflow",
    )


def advice(
    disposition: FailureDisposition,
    confidence: float,
) -> SupervisorFailureAdvice:
    return SupervisorFailureAdvice(
        disposition=disposition,
        confidence=confidence,
        probabilities={
            FailureDisposition.RETRY: (
                confidence
                if disposition is FailureDisposition.RETRY
                else 1.0 - confidence
            ),
            FailureDisposition.STOP: (
                confidence
                if disposition is FailureDisposition.STOP
                else 1.0 - confidence
            ),
        },
        model="jev-latest",
        latency_ms=10,
    )


def guarded_policy(
    primary: AsyncMock,
    advisor: AsyncMock,
    sink: AsyncMock,
) -> GuardedSupervisorPolicy:
    return GuardedSupervisorPolicy(
        primary=primary,
        advisor=advisor,
        observation_sink=sink,
        confidence_threshold=0.8,
    )


def test_high_confidence_stop_advice_vetoes_rule_retry() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = retry_decision()
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.STOP,
        0.95,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        guarded_policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    assert result.action is SupervisorAction.FAIL
    assert result.next_step is SupervisorStep.FINISH
    assert result.status is WorkflowStatus.FAILED
    sink.record.assert_awaited_once()


def test_low_confidence_stop_advice_does_not_veto_retry() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = retry_decision()
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.STOP,
        0.7,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        guarded_policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    assert result is primary.decide.return_value


def test_guard_never_turns_rule_stop_into_retry() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = fail_decision()
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.RETRY,
        0.99,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        guarded_policy(primary, advisor, sink).decide(
            failed_state(retryable=False),
            WorkflowStatus.FAILED,
        )
    )

    assert result is primary.decide.return_value
    assert result.action is SupervisorAction.FAIL


def test_guard_keeps_rule_decision_when_jev_fails() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = retry_decision()
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.side_effect = TimeoutError("Jev timed out")
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        guarded_policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    assert result is primary.decide.return_value
    observation = sink.record.await_args.args[0]
    assert observation.error == "Jev timed out"


def test_guard_does_not_veto_retry_when_audit_write_fails() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = retry_decision()
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.STOP,
        0.99,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)
    sink.record.side_effect = RuntimeError("database unavailable")

    result = asyncio.run(
        guarded_policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    assert result is primary.decide.return_value
    assert result.action is SupervisorAction.RETRY
