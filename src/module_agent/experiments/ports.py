from typing import Protocol

from module_agent.experiments.domain import ExperimentPlan, StepResult


class ExperimentRunner(Protocol):
    """Runs one step; cancellation must remove the owned sandbox container."""

    async def execute(
        self,
        plan: ExperimentPlan,
        name: str,
        argv: list[str],
    ) -> StepResult: ...
