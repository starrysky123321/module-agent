import asyncio
from unittest.mock import AsyncMock

import pytest

from module_agent.supervision.application.shadow_policy import (
    ShadowSupervisorPolicy,
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
        attempt=1,
        error_type="TimeoutError",
    )
    return {
        "literature_run_id": 7,
        "status": WorkflowStatus.FAILED.value,
        "failure": failure.model_dump(mode="json"),
    }


def decision(action: SupervisorAction) -> SupervisorDecision:
    if action is SupervisorAction.RETRY:
        return SupervisorDecision(
            action=action,
            next_step=SupervisorStep.VALIDATION,
            status=WorkflowStatus.VALIDATING,
            reason="Retry validation",
        )
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
    selected_probability = confidence
    other_probability = 1.0 - confidence
    return SupervisorFailureAdvice(
        disposition=disposition,
        confidence=confidence,
        probabilities={
            disposition: selected_probability,
            (
                FailureDisposition.STOP
                if disposition is FailureDisposition.RETRY
                else FailureDisposition.RETRY
            ): other_probability,
        },
        model="jev-latest",
        latency_ms=20,
    )


def policy(
    primary: AsyncMock,
    advisor: AsyncMock,
    sink: AsyncMock,
    *,
    threshold: float = 0.8,
) -> ShadowSupervisorPolicy:
    return ShadowSupervisorPolicy(
        primary=primary,
        advisor=advisor,
        observation_sink=sink,
        confidence_threshold=threshold,
    )


def test_shadow_policy_skips_jev_for_non_failed_state() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = SupervisorDecision(
        action=SupervisorAction.ROUTE,
        next_step=SupervisorStep.CODE,
        status=WorkflowStatus.PREPARING_CODE,
        reason="Run code",
    )
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    sink = AsyncMock(spec=SupervisorObservationSink)
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.PREPARING_CODE.value,
    }

    result = asyncio.run(
        policy(primary, advisor, sink).decide(
            state,
            WorkflowStatus.PREPARING_CODE,
        )
    )

    assert result is primary.decide.return_value
    advisor.advise.assert_not_awaited()
    sink.record.assert_not_awaited()


def test_shadow_policy_records_high_confidence_agreement() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = decision(SupervisorAction.RETRY)
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.RETRY,
        0.91,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    observation = sink.record.await_args.args[0]
    assert result is primary.decide.return_value
    assert observation.agrees is True
    assert observation.meets_confidence_threshold is True
    assert observation.rule_disposition is FailureDisposition.RETRY


def test_shadow_policy_records_low_confidence_disagreement() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = decision(SupervisorAction.FAIL)
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.RETRY,
        0.6,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        policy(primary, advisor, sink).decide(
            failed_state(retryable=False),
            WorkflowStatus.FAILED,
        )
    )

    observation = sink.record.await_args.args[0]
    assert result.action is SupervisorAction.FAIL
    assert observation.agrees is False
    assert observation.meets_confidence_threshold is False


def test_shadow_policy_records_jev_error_and_keeps_rule_decision() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = decision(SupervisorAction.RETRY)
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.side_effect = TimeoutError("Jev timed out")
    sink = AsyncMock(spec=SupervisorObservationSink)

    result = asyncio.run(
        policy(primary, advisor, sink).decide(
            failed_state(retryable=True),
            WorkflowStatus.FAILED,
        )
    )

    observation = sink.record.await_args.args[0]
    assert result.action is SupervisorAction.RETRY
    assert observation.advice is None
    assert observation.error == "Jev timed out"


def test_shadow_policy_ignores_observation_sink_failure() -> None:
    primary = AsyncMock(spec=SupervisorDecisionPolicy)
    primary.decide.return_value = decision(SupervisorAction.FAIL)
    advisor = AsyncMock(spec=SupervisorFailureAdvisor)
    advisor.advise.return_value = advice(
        FailureDisposition.STOP,
        0.9,
    )
    sink = AsyncMock(spec=SupervisorObservationSink)
    sink.record.side_effect = RuntimeError("Sink unavailable")

    result = asyncio.run(
        policy(primary, advisor, sink).decide(
            failed_state(retryable=False),
            WorkflowStatus.FAILED,
        )
    )

    assert result.action is SupervisorAction.FAIL


@pytest.mark.parametrize("threshold", [-0.1, 1.1, True])
def test_shadow_policy_rejects_invalid_threshold(
    threshold: float,
) -> None:
    with pytest.raises(ValueError, match="between 0 and 1"):
        ShadowSupervisorPolicy(
            primary=AsyncMock(spec=SupervisorDecisionPolicy),
            advisor=AsyncMock(spec=SupervisorFailureAdvisor),
            observation_sink=AsyncMock(spec=SupervisorObservationSink),
            confidence_threshold=threshold,
        )
