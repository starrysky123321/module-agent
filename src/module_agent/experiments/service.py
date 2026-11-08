"""One explicitly approved, durable pilot; no implicit downloads or retries."""

import asyncio
import math
from secrets import compare_digest

from module_agent.experiments.domain import (
    ExperimentConsent,
    ExperimentPlan,
    ExperimentResult,
    ExperimentStatus,
    StepResult,
)
from module_agent.experiments.mnist import (
    environment_command,
    evaluation_command,
    structured_stdout,
    train_command,
)
from module_agent.experiments.ports import ExperimentRunner
from module_agent.experiments.workspace import ExperimentWorkspace


class ExperimentService:
    def __init__(
        self, workspace: ExperimentWorkspace, runner: ExperimentRunner
    ) -> None:
        self.workspace, self.runner = workspace, runner

    async def execute(
        self, plan: ExperimentPlan, consent: ExperimentConsent
    ) -> ExperimentResult:
        if not compare_digest(plan.digest(), consent.plan_sha256):
            raise ValueError("Authorization does not match the frozen experiment plan")
        with self.workspace.execution_lock():
            return await self._execute_approved(plan, consent)

    async def _execute_approved(
        self, plan: ExperimentPlan, consent: ExperimentConsent
    ) -> ExperimentResult:
        # Exclusive run directory prevents duplicate execution, even across CLI processes.
        run = self.workspace.snapshot(plan)
        self.workspace.save_json(run / "consent.json", consent.model_dump(mode="json"))
        steps: list[StepResult] = []
        stage = "preparing"

        def save(status: ExperimentStatus, *, error: str | None = None):
            result = ExperimentResult(
                plan_id=plan.id,
                plan_sha256=plan.digest(),
                status=status,
                stage=stage,
                steps=tuple(steps),
                error=error,
            )
            self.workspace.save_json(
                run / "result.json", result.model_dump(mode="json")
            )
            return result

        save(ExperimentStatus.RUNNING)
        try:
            async with asyncio.timeout(plan.budget.timeout_seconds):
                for stage, command in (
                    ("environment", environment_command()),
                    ("train", train_command(plan)),
                    ("evaluate", evaluation_command(plan)),
                ):
                    save(ExperimentStatus.RUNNING)
                    step = await self.runner.execute(plan, stage, command)
                    if step.name != stage:
                        raise ValueError(
                            "Runner returned a result for a different stage"
                        )
                    steps.append(step)
                    self.workspace.save_json(
                        run / f"step-{stage}.json", step.model_dump(mode="json")
                    )
                    if step.exit_code != 0:
                        raise ValueError(
                            f"Experiment {stage} failed (exit {step.exit_code})"
                        )
                    if stage == "environment":
                        environment = structured_stdout(
                            step.stdout, "MODULE_AGENT_ENV="
                        )
                        self.workspace.save_json(run / "environment.json", environment)
                stage = "collecting"
                metrics = self.workspace.collect(plan)
                measured = structured_stdout(steps[-1].stdout, "MODULE_AGENT_EVAL=")
                for field in (
                    "evaluated_samples",
                    "correct",
                    "wrong",
                    "accuracy_percent",
                    "checkpoint_sha256",
                ):
                    actual = measured.get(field)
                    expected = getattr(metrics, field)
                    equal = (
                        math.isclose(actual, expected, abs_tol=1e-8, rel_tol=0)
                        if field == "accuracy_percent"
                        and isinstance(actual, (int, float))
                        else actual == expected
                    )
                    if not equal:
                        raise ValueError(
                            "Independent evaluation and saved artifacts disagree"
                        )
                self.workspace.save_json(
                    run / "metrics.json", metrics.model_dump(mode="json")
                )
                result = ExperimentResult(
                    plan_id=plan.id,
                    plan_sha256=plan.digest(),
                    status=ExperimentStatus.COMPLETED,
                    stage="finished",
                    steps=tuple(steps),
                    metrics=metrics,
                )
                self.workspace.save_json(
                    run / "result.json", result.model_dump(mode="json")
                )
                return result
        except asyncio.CancelledError:
            save(
                ExperimentStatus.CANCELLED,
                error="实验已停止，保留现有产物；不自动重新训练。",
            )
            raise
        except TimeoutError:
            return save(
                ExperimentStatus.TIMED_OUT,
                error="实验超过批准的总时间预算，已停止；结果不可标记为复现成功。",
            )
        except Exception as error:
            # No automatic replay of code or environment preparation.
            return save(
                ExperimentStatus.FAILED, error=str(error)[:1000] or type(error).__name__
            )
