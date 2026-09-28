import asyncio
from unittest.mock import AsyncMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from module_agent.code.application.agent import CodeAgent
from module_agent.literature.application.dispatch import (
    LiteratureRunDispatcher,
)
from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecision,
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.validation.application.agent import ValidationAgent
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)
from module_agent.workflow.graph import ModuleBuildWorkflow


def workflow(supervisor_agent: AsyncMock) -> ModuleBuildWorkflow:
    return ModuleBuildWorkflow(
        literature_dispatcher=AsyncMock(spec=LiteratureRunDispatcher),
        code_agent=AsyncMock(spec=CodeAgent),
        validation_agent=AsyncMock(spec=ValidationAgent),
        code_input_loader=AsyncMock(spec=SelectedPaperCodeInputLoader),
        supervisor_agent=supervisor_agent,
        checkpointer=InMemorySaver(),
    )


def test_workflow_registers_supervisor_node() -> None:
    supervisor_agent = AsyncMock(spec=SupervisorAgent)

    graph = workflow(supervisor_agent).build()

    assert "supervisor" in graph.nodes


def test_supervisor_node_persists_serializable_decision() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.CODE_READY.value,
        "next_step": SupervisorStep.VALIDATION.value,
        "selected_paper_ids": [1],
        "code_artifacts": [{"paper_id": 1}],
    }
    decision = SupervisorDecision(
        action=SupervisorAction.ROUTE,
        next_step=SupervisorStep.VALIDATION,
        status=WorkflowStatus.VALIDATING,
        reason="Code artifacts are ready for validation",
    )
    supervisor_agent = AsyncMock(spec=SupervisorAgent)
    supervisor_agent.run.return_value = decision
    module_workflow = workflow(supervisor_agent)

    result = asyncio.run(module_workflow._supervisor_node(state))

    supervisor_agent.run.assert_awaited_once_with(state)
    assert result == {
        "supervisor_decision": {
            "action": "route",
            "next_step": "validation",
            "status": "validating",
            "reason": "Code artifacts are ready for validation",
        },
        "status": "validating",
        "next_step": "validation",
    }


def test_supervisor_retry_clears_failure_without_mutating_attempts() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=True,
        attempt=1,
        error_type="TimeoutError",
    )
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.FAILED.value,
        "next_step": SupervisorStep.FINISH.value,
        "attempts": {SupervisorStep.VALIDATION.value: 1},
        "failure": failure.model_dump(mode="json"),
    }
    decision = SupervisorDecision(
        action=SupervisorAction.RETRY,
        next_step=SupervisorStep.VALIDATION,
        status=WorkflowStatus.VALIDATING,
        reason="Retry validation",
    )
    supervisor_agent = AsyncMock(spec=SupervisorAgent)
    supervisor_agent.run.return_value = decision

    result = asyncio.run(
        workflow(supervisor_agent)._supervisor_node(state)
    )

    assert result["failure"] is None
    assert result["status"] == WorkflowStatus.VALIDATING.value
    assert state["attempts"] == {SupervisorStep.VALIDATION.value: 1}


@pytest.mark.parametrize(
    ("decision", "expected_route"),
    [
        (
            SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.LITERATURE,
                status=WorkflowStatus.SEARCHING_LITERATURE,
                reason="Start literature search",
            ),
            "literature_dispatch",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.WAIT,
                next_step=SupervisorStep.LITERATURE,
                status=WorkflowStatus.SEARCHING_LITERATURE,
                reason="Wait for literature search",
            ),
            "literature_wait",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.WAIT,
                next_step=SupervisorStep.PAPER_SELECTION,
                status=WorkflowStatus.WAITING_FOR_PAPER_SELECTION,
                reason="Wait for paper selection",
            ),
            "paper_selection",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.ROUTE,
                next_step=SupervisorStep.CODE,
                status=WorkflowStatus.PREPARING_CODE,
                reason="Build code artifacts",
            ),
            "code",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.RETRY,
                next_step=SupervisorStep.VALIDATION,
                status=WorkflowStatus.VALIDATING,
                reason="Retry validation",
            ),
            "validation",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.FINISH,
                next_step=SupervisorStep.FINISH,
                status=WorkflowStatus.COMPLETED,
                reason="Workflow completed",
            ),
            "finish",
        ),
        (
            SupervisorDecision(
                action=SupervisorAction.FAIL,
                next_step=SupervisorStep.FINISH,
                status=WorkflowStatus.FAILED,
                reason="Workflow failed",
            ),
            "finish",
        ),
    ],
)
def test_route_supervisor_maps_decision_to_graph_route(
    decision: SupervisorDecision,
    expected_route: str,
) -> None:
    module_workflow = workflow(AsyncMock(spec=SupervisorAgent))
    state: ModuleGraphState = {
        "supervisor_decision": decision.model_dump(mode="json"),
    }

    assert module_workflow._route_supervisor(state) == expected_route


def test_route_supervisor_rejects_missing_decision() -> None:
    module_workflow = workflow(AsyncMock(spec=SupervisorAgent))

    with pytest.raises(
        ValueError,
        match="Workflow has no supervisor decision",
    ):
        module_workflow._route_supervisor(ModuleGraphState())


def test_record_attempt_starts_stage_at_one() -> None:
    state: ModuleGraphState = {}

    attempts, current = ModuleBuildWorkflow._record_attempt(
        state,
        SupervisorStep.CODE,
    )

    assert attempts == {SupervisorStep.CODE.value: 1}
    assert current == 1
    assert "attempts" not in state


def test_record_attempt_increments_copy_without_mutating_state() -> None:
    state: ModuleGraphState = {
        "attempts": {
            SupervisorStep.LITERATURE.value: 1,
            SupervisorStep.VALIDATION.value: 1,
        }
    }

    attempts, current = ModuleBuildWorkflow._record_attempt(
        state,
        SupervisorStep.VALIDATION,
    )

    assert attempts == {
        SupervisorStep.LITERATURE.value: 1,
        SupervisorStep.VALIDATION.value: 2,
    }
    assert current == 2
    assert state["attempts"] == {
        SupervisorStep.LITERATURE.value: 1,
        SupervisorStep.VALIDATION.value: 1,
    }


@pytest.mark.parametrize(
    ("current_attempt", "retryable"),
    [(1, True), (2, False)],
)
def test_failure_result_respects_retry_budget(
    current_attempt: int,
    retryable: bool,
) -> None:
    module_workflow = workflow(AsyncMock(spec=SupervisorAgent))
    attempts = {
        SupervisorStep.VALIDATION.value: current_attempt,
    }

    result = module_workflow._failure_result(
        step=SupervisorStep.VALIDATION,
        exc=TimeoutError("Validation timed out"),
        attempts=attempts,
        current_attempt=current_attempt,
    )
    failure = WorkflowFailure.model_validate(result["failure"])

    assert result["attempts"] == attempts
    assert result["status"] == WorkflowStatus.FAILED.value
    assert failure.step is SupervisorStep.VALIDATION
    assert failure.category is WorkflowFailureCategory.TIMEOUT
    assert failure.attempt == current_attempt
    assert failure.retryable is retryable
