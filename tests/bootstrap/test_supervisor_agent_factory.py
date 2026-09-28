from unittest.mock import MagicMock

import pytest
from typesafe_sdk import AsyncTypeSafeClient

from module_agent.bootstrap.factories.supervisor_agent import (
    build_supervisor_agent,
)
from module_agent.shared.decision.typesafe_client import (
    TypeSafeClientManager,
)
from module_agent.supervision.adapters.jev_failure_advisor import (
    JevFailureAdvisor,
)
from module_agent.supervision.adapters.logging_observation import (
    LoggingSupervisorObservationSink,
)
from module_agent.supervision.application.rule_policy import (
    RuleBasedSupervisorPolicy,
)
from module_agent.supervision.application.shadow_policy import (
    ShadowSupervisorPolicy,
)
from module_agent.supervision.application.guarded_policy import (
    GuardedSupervisorPolicy,
)
from module_agent.supervision.domain import SupervisorObservationSink


def test_rule_mode_does_not_create_typesafe_client() -> None:
    manager = MagicMock(spec=TypeSafeClientManager)

    agent = build_supervisor_agent(
        mode="rule",
        typesafe_client_manager=manager,
        confidence_threshold=0.8,
    )

    assert isinstance(agent.policy, RuleBasedSupervisorPolicy)
    manager.get_client.assert_not_called()


def test_jev_shadow_mode_builds_shadow_policy() -> None:
    manager = MagicMock(spec=TypeSafeClientManager)
    client = MagicMock(spec=AsyncTypeSafeClient)
    manager.get_client.return_value = client

    agent = build_supervisor_agent(
        mode="jev_shadow",
        typesafe_client_manager=manager,
        confidence_threshold=0.75,
    )

    assert isinstance(agent.policy, ShadowSupervisorPolicy)
    assert isinstance(agent.policy.primary, RuleBasedSupervisorPolicy)
    assert isinstance(agent.policy.advisor, JevFailureAdvisor)
    assert agent.policy.advisor.client is client
    assert isinstance(
        agent.policy.observation_sink,
        LoggingSupervisorObservationSink,
    )
    assert agent.policy.confidence_threshold == 0.75
    manager.get_client.assert_called_once_with()


def test_jev_shadow_mode_uses_injected_observation_sink() -> None:
    manager = MagicMock(spec=TypeSafeClientManager)
    manager.get_client.return_value = MagicMock(
        spec=AsyncTypeSafeClient
    )
    observation_sink = MagicMock(spec=SupervisorObservationSink)

    agent = build_supervisor_agent(
        mode="jev_shadow",
        typesafe_client_manager=manager,
        confidence_threshold=0.8,
        observation_sink=observation_sink,
    )

    assert isinstance(agent.policy, ShadowSupervisorPolicy)
    assert agent.policy.observation_sink is observation_sink


def test_jev_guarded_mode_builds_guarded_policy() -> None:
    manager = MagicMock(spec=TypeSafeClientManager)
    manager.get_client.return_value = MagicMock(
        spec=AsyncTypeSafeClient
    )
    observation_sink = MagicMock(spec=SupervisorObservationSink)

    agent = build_supervisor_agent(
        mode="jev_guarded",
        typesafe_client_manager=manager,
        confidence_threshold=0.9,
        observation_sink=observation_sink,
    )

    assert isinstance(agent.policy, GuardedSupervisorPolicy)
    assert agent.policy.observation_sink is observation_sink
    assert agent.policy.confidence_threshold == 0.9


def test_unknown_supervisor_mode_is_rejected() -> None:
    manager = MagicMock(spec=TypeSafeClientManager)

    with pytest.raises(ValueError, match="Unsupported supervisor"):
        build_supervisor_agent(
            mode="unknown",
            typesafe_client_manager=manager,
            confidence_threshold=0.8,
        )

    manager.get_client.assert_not_called()
