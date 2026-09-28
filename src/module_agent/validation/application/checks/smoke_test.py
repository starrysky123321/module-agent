from collections.abc import Sequence
from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.ports import SandboxRunner
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import SandboxExecutionRequest


class SmokeTestCheck:
    """Run one explicit user-approved smoke command inside the sandbox."""

    def __init__(
        self,
        runner: SandboxRunner,
        policy: ValidationPolicy,
        argv: Sequence[str],
        *,
        working_directory: str = ".",
    ) -> None:
        """初始化当前对象。"""
        if policy.mode is not ValidationMode.SANDBOX:
            raise ValueError(
                "SmokeTestCheck requires sandbox validation mode"
            )
        if not argv:
            raise ValueError("SmokeTestCheck requires a command")

        self.runner = runner
        self.policy = policy
        self.argv = tuple(argv)
        self.working_directory = working_directory

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.SMOKE_TEST

    def supports(self, artifact: CodeArtifact) -> bool:
        """判断当前检查器是否支持该产物。"""
        return artifact.status in {
            CodeArtifactStatus.REPOSITORY_READY,
            CodeArtifactStatus.REPRODUCTION_PLANNED,
        }

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        """执行当前任务。"""
        if artifact.local_path is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository artifact has no local path",
            )

        request = SandboxExecutionRequest(
            repository_path=Path(artifact.local_path),
            argv=list(self.argv),
            working_directory=self.working_directory,
            policy=self.policy,
        )
        result = await self.runner.execute(request)
        details: dict[str, object] = {
            "working_directory": self.working_directory,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        }
        command = f"{self.argv[0]} <smoke-test-arguments>"

        if result.timed_out:
            status = ValidationCheckStatus.FAILED
            summary = "Smoke test timed out"
        elif result.exit_code != 0:
            status = ValidationCheckStatus.FAILED
            summary = "Smoke test failed"
        else:
            status = ValidationCheckStatus.PASSED
            summary = "Smoke test passed"

        return ValidationCheck(
            kind=self.kind,
            status=status,
            summary=summary,
            details=details,
            command=command,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
