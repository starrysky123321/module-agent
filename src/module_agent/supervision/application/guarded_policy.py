from module_agent.supervision.application.shadow_policy import (
    ShadowSupervisorPolicy,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorAction,
    SupervisorDecision,
    SupervisorFailureObservation,
)
from module_agent.workflow.domain import (
    SupervisorStep,
    WorkflowStatus,
)


class GuardedSupervisorPolicy(ShadowSupervisorPolicy):
    """Allow high-confidence Jev advice to veto retries, never add them."""

    def apply_advice(
        self,
        decision: SupervisorDecision,
        observation: SupervisorFailureObservation,
    ) -> SupervisorDecision:
        """在安全边界内应用外部决策建议。"""
        advice = observation.advice
        if (
            advice is None
            or observation.meets_confidence_threshold is not True
            or decision.action is not SupervisorAction.RETRY
            or advice.disposition is not FailureDisposition.STOP
        ):
            return decision

        return SupervisorDecision(
            action=SupervisorAction.FAIL,
            next_step=SupervisorStep.FINISH,
            status=WorkflowStatus.FAILED,
            reason=(
                "Jev safety guard stopped the retry for "
                f"{observation.failure.step.value} with "
                f"confidence {advice.confidence:.2f}"
            ),
        )
