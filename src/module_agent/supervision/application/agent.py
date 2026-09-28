from module_agent.supervision.application.rule_policy import (
    RuleBasedSupervisorPolicy,
)
from module_agent.supervision.application.state_validator import (
    WorkflowStateValidator,
)
from module_agent.supervision.domain import (
    SupervisorDecision,
    SupervisorDecisionPolicy,
)
from module_agent.workflow.domain import ModuleGraphState


class SupervisorAgent:
    """决定 Workflow 下一步应交给哪个专业 Agent。"""

    def __init__(
        self,
        policy: SupervisorDecisionPolicy | None = None,
        state_validator: WorkflowStateValidator | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.policy = policy or RuleBasedSupervisorPolicy()
        self.state_validator = (
            state_validator or WorkflowStateValidator()
        )

    async def run(
        self,
        state: ModuleGraphState,
    ) -> SupervisorDecision:
        """执行当前任务。"""
        status = self.state_validator.validate(state)

        return await self.policy.decide(
            state,
            status,
        )
