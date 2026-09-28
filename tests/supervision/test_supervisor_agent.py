import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.supervision.application.state_validator import (
    WorkflowStateValidator,
)
from module_agent.supervision.domain import (
    SupervisorAction,
    SupervisorDecision,
    SupervisorDecisionPolicy,
)
from module_agent.workflow.domain import (
    ModuleGraphState,
    SupervisorStep,
    WorkflowStatus,
)


def decision() -> SupervisorDecision:
    return SupervisorDecision(
        action=SupervisorAction.ROUTE,
        next_step=SupervisorStep.CODE,
        status=WorkflowStatus.PREPARING_CODE,
        reason="Selected papers are ready",
    )


def test_agent_validates_state_before_calling_injected_policy() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.PREPARING_CODE.value,
        "selected_paper_ids": [1],
    }
    validator = MagicMock(spec=WorkflowStateValidator)
    validator.validate.return_value = WorkflowStatus.PREPARING_CODE
    policy = AsyncMock(spec=SupervisorDecisionPolicy)
    expected = decision()
    policy.decide.return_value = expected
    agent = SupervisorAgent(
        policy=policy,
        state_validator=validator,
    )

    result = asyncio.run(agent.run(state))

    assert result == expected
    validator.validate.assert_called_once_with(state)
    policy.decide.assert_awaited_once_with(
        state,
        WorkflowStatus.PREPARING_CODE,
    )


def test_agent_does_not_call_policy_for_invalid_state() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.PREPARING_CODE.value,
    }
    validator = MagicMock(spec=WorkflowStateValidator)
    validator.validate.side_effect = ValueError("Invalid state")
    policy = AsyncMock(spec=SupervisorDecisionPolicy)
    agent = SupervisorAgent(
        policy=policy,
        state_validator=validator,
    )

    with pytest.raises(ValueError, match="Invalid state"):
        asyncio.run(agent.run(state))

    policy.decide.assert_not_awaited()


def test_default_agent_uses_rule_policy() -> None:
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "status": WorkflowStatus.CREATED.value,
    }

    result = asyncio.run(SupervisorAgent().run(state))

    assert result.action is SupervisorAction.ROUTE
    assert result.next_step is SupervisorStep.LITERATURE
    assert result.status is WorkflowStatus.SEARCHING_LITERATURE
