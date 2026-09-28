import asyncio

import pytest

from module_agent.supervision.application.rule_policy import (
    RuleBasedSupervisorPolicy,
)
from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecisionPolicy,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)


@pytest.mark.parametrize(
    ("status", "action", "next_step", "decision_status"),
    [
        (
            WorkflowStatus.CREATED,
            SupervisorAction.ROUTE,
            SupervisorStep.LITERATURE,
            WorkflowStatus.SEARCHING_LITERATURE,
        ),
        (
            WorkflowStatus.SEARCHING_LITERATURE,
            SupervisorAction.ROUTE,
            SupervisorStep.LITERATURE,
            WorkflowStatus.SEARCHING_LITERATURE,
        ),
        (
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
            SupervisorAction.WAIT,
            SupervisorStep.PAPER_SELECTION,
            WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
        ),
        (
            WorkflowStatus.PREPARING_CODE,
            SupervisorAction.ROUTE,
            SupervisorStep.CODE,
            WorkflowStatus.PREPARING_CODE,
        ),
        (
            WorkflowStatus.CODE_READY,
            SupervisorAction.ROUTE,
            SupervisorStep.VALIDATION,
            WorkflowStatus.VALIDATING,
        ),
        (
            WorkflowStatus.VALIDATING,
            SupervisorAction.ROUTE,
            SupervisorStep.VALIDATION,
            WorkflowStatus.VALIDATING,
        ),
        (
            WorkflowStatus.COMPLETED,
            SupervisorAction.FINISH,
            SupervisorStep.FINISH,
            WorkflowStatus.COMPLETED,
        ),
    ],
)
def test_rule_policy_returns_expected_decision_for_each_status(
    status: WorkflowStatus,
    action: SupervisorAction,
    next_step: SupervisorStep,
    decision_status: WorkflowStatus,
) -> None:
    state: ModuleGraphState = {"status": status.value}
    policy: SupervisorDecisionPolicy = RuleBasedSupervisorPolicy()

    decision = asyncio.run(policy.decide(state, status))

    assert decision.action is action
    assert decision.next_step is next_step
    assert decision.status is decision_status
    assert decision.reason


def test_dispatched_literature_search_waits_instead_of_redispatching() -> None:
    state: ModuleGraphState = {
        "status": WorkflowStatus.SEARCHING_LITERATURE.value,
        "literature_message_id": "message-7",
    }
    policy = RuleBasedSupervisorPolicy()

    decision = asyncio.run(
        policy.decide(state, WorkflowStatus.SEARCHING_LITERATURE)
    )

    assert decision.action is SupervisorAction.WAIT
    assert decision.next_step is SupervisorStep.LITERATURE
    assert decision.status is WorkflowStatus.SEARCHING_LITERATURE


@pytest.mark.parametrize("message_id", [None, "", "   "])
def test_missing_message_id_routes_literature_dispatch(
    message_id: str | None,
) -> None:
    state: ModuleGraphState = {
        "status": WorkflowStatus.SEARCHING_LITERATURE.value,
    }
    if message_id is not None:
        state["literature_message_id"] = message_id

    decision = asyncio.run(
        RuleBasedSupervisorPolicy().decide(
            state,
            WorkflowStatus.SEARCHING_LITERATURE,
        )
    )

    assert decision.action is SupervisorAction.ROUTE


def test_rule_policy_does_not_mutate_workflow_state() -> None:
    state: ModuleGraphState = {
        "status": WorkflowStatus.PREPARING_CODE.value,
        "selected_paper_ids": [1],
    }
    original = dict(state)

    asyncio.run(
        RuleBasedSupervisorPolicy().decide(
            state,
            WorkflowStatus.PREPARING_CODE,
        )
    )

    assert state == original


def test_retryable_failure_returns_to_failed_step() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=True,
        attempt=1,
        error_type="TimeoutError",
    )
    state: ModuleGraphState = {
        "status": WorkflowStatus.FAILED.value,
        "failure": failure.model_dump(mode="json"),
    }

    decision = asyncio.run(
        RuleBasedSupervisorPolicy().decide(
            state,
            WorkflowStatus.FAILED,
        )
    )

    assert decision.action is SupervisorAction.RETRY
    assert decision.next_step is SupervisorStep.VALIDATION
    assert decision.status is WorkflowStatus.VALIDATING
    assert "attempt 1" in decision.reason


def test_non_retryable_failure_finishes_workflow() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.CODE,
        category=WorkflowFailureCategory.INTERNAL,
        message="Code preparation failed",
        retryable=False,
        attempt=1,
        error_type="RuntimeError",
    )
    state: ModuleGraphState = {
        "status": WorkflowStatus.FAILED.value,
        "failure": failure.model_dump(mode="json"),
    }

    decision = asyncio.run(
        RuleBasedSupervisorPolicy().decide(
            state,
            WorkflowStatus.FAILED,
        )
    )

    assert decision.action is SupervisorAction.FAIL
    assert decision.next_step is SupervisorStep.FINISH
    assert decision.status is WorkflowStatus.FAILED
    assert "Code preparation failed" in decision.reason
