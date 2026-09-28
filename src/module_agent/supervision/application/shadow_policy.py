from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorAction,
    SupervisorDecision,
    SupervisorDecisionPolicy,
    SupervisorFailureAdvisor,
    SupervisorFailureObservation,
    SupervisorObservationSink,
    WorkflowFailure,
)
from module_agent.workflow.domain import ModuleGraphState, WorkflowStatus


class ShadowSupervisorPolicy:
    """Observe Jev advice while always executing the primary policy."""

    def __init__(
        self,
        *,
        primary: SupervisorDecisionPolicy,
        advisor: SupervisorFailureAdvisor,
        observation_sink: SupervisorObservationSink,
        confidence_threshold: float,
    ) -> None:
        """初始化当前对象。"""
        if (
            isinstance(confidence_threshold, bool)
            or not isinstance(confidence_threshold, (int, float))
            or not 0.0 <= confidence_threshold <= 1.0
        ):
            raise ValueError(
                "confidence_threshold must be between 0 and 1"
            )

        self.primary = primary
        self.advisor = advisor
        self.observation_sink = observation_sink
        self.confidence_threshold = float(confidence_threshold)

    async def decide(
        self,
        state: ModuleGraphState,
        status: WorkflowStatus,
    ) -> SupervisorDecision:
        """根据当前状态生成决策。"""
        decision = await self.primary.decide(state, status)

        observation = await self._observe_failure(
            state,
            status,
            decision,
        )
        if observation is None:
            return decision

        try:
            await self.observation_sink.record(observation)
        except Exception:
            # An unrecorded recommendation must never change execution.
            return decision

        return self.apply_advice(decision, observation)

    async def _observe_failure(
        self,
        state: ModuleGraphState,
        status: WorkflowStatus,
        decision: SupervisorDecision,
    ) -> SupervisorFailureObservation | None:

        if status is not WorkflowStatus.FAILED:
            return None

        literature_run_id = state.get("literature_run_id")
        if (
            type(literature_run_id) is not int
            or literature_run_id <= 0
        ):
            return None

        failure = WorkflowFailure.model_validate(state.get("failure"))
        rule_disposition = (
            FailureDisposition.RETRY
            if decision.action is SupervisorAction.RETRY
            else FailureDisposition.STOP
        )

        try:
            advice = await self.advisor.advise(failure)
        except Exception as exc:
            observation = SupervisorFailureObservation(
                literature_run_id=literature_run_id,
                failure=failure,
                rule_disposition=rule_disposition,
                error=(str(exc).strip() or type(exc).__name__)[:1000],
            )
        else:
            observation = SupervisorFailureObservation(
                literature_run_id=literature_run_id,
                failure=failure,
                rule_disposition=rule_disposition,
                advice=advice,
                agrees=advice.disposition is rule_disposition,
                meets_confidence_threshold=(
                    advice.confidence >= self.confidence_threshold
                ),
            )

        return observation

    def apply_advice(
        self,
        decision: SupervisorDecision,
        observation: SupervisorFailureObservation,
    ) -> SupervisorDecision:
        """在安全边界内应用外部决策建议。"""
        return decision
