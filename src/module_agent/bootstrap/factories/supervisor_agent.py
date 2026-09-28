from module_agent.shared.decision.typesafe_client import (
    TypeSafeClientManager,
)
from module_agent.supervision.adapters.jev_failure_advisor import (
    JevFailureAdvisor,
)
from module_agent.supervision.adapters.logging_observation import (
    LoggingSupervisorObservationSink,
)
from module_agent.supervision.application.agent import SupervisorAgent
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


def build_supervisor_agent(
    *,
    mode: str,
    typesafe_client_manager: TypeSafeClientManager,
    confidence_threshold: float,
    observation_sink: SupervisorObservationSink | None = None,
) -> SupervisorAgent:
    """构建并返回目标对象。"""
    primary = RuleBasedSupervisorPolicy()

    if mode == "rule":
        return SupervisorAgent(policy=primary)

    if mode in {"jev_shadow", "jev_guarded"}:
        policy_type = (
            ShadowSupervisorPolicy
            if mode == "jev_shadow"
            else GuardedSupervisorPolicy
        )
        policy = policy_type(
            primary=primary,
            advisor=JevFailureAdvisor(
                typesafe_client_manager.get_client()
            ),
            observation_sink=(
                observation_sink
                if observation_sink is not None
                else LoggingSupervisorObservationSink()
            ),
            confidence_threshold=confidence_threshold,
        )
        return SupervisorAgent(policy=policy)

    raise ValueError(
        f"Unsupported supervisor policy mode: {mode}"
    )
