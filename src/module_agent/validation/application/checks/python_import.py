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


class PythonImportCheck:
    """Import only user-approved modules inside the execution sandbox."""

    IMPORT_SCRIPT = "\n".join(
        [
            "import importlib",
            "import pathlib",
            "import sys",
            "",
            "src = pathlib.Path('src')",
            "if src.is_dir():",
            "    sys.path.insert(0, str(src.resolve()))",
            "",
            "failures = 0",
            "for module_name in sys.argv[1:]:",
            "    try:",
            "        importlib.import_module(module_name)",
            "    except BaseException as exc:",
            "        failures += 1",
            "        print(",
            "            f'{module_name}: {type(exc).__name__}: {exc}',",
            "            file=sys.stderr,",
            "        )",
            "",
            "print(f'imported={len(sys.argv) - 1 - failures}')",
            "print(f'failed={failures}')",
            "raise SystemExit(1 if failures else 0)",
        ]
    )

    def __init__(
        self,
        runner: SandboxRunner,
        policy: ValidationPolicy,
        modules: Sequence[str],
    ) -> None:
        """初始化当前对象。"""
        if policy.mode is not ValidationMode.SANDBOX:
            raise ValueError(
                "PythonImportCheck requires sandbox validation mode"
            )
        if not modules:
            raise ValueError(
                "PythonImportCheck requires at least one module"
            )

        self.runner = runner
        self.policy = policy
        self.modules = tuple(modules)

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.IMPORT

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
            argv=["python", "-c", self.IMPORT_SCRIPT, *self.modules],
            policy=self.policy,
        )
        result = await self.runner.execute(request)
        details: dict[str, object] = {
            "modules": list(self.modules),
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        }
        command = "python -c <import-check> " + " ".join(self.modules)

        if result.timed_out:
            status = ValidationCheckStatus.FAILED
            summary = "Python import check timed out"
        elif result.exit_code != 0:
            status = ValidationCheckStatus.FAILED
            summary = "Python import check failed"
        else:
            status = ValidationCheckStatus.PASSED
            summary = "Requested Python modules imported successfully"

        return ValidationCheck(
            kind=self.kind,
            status=status,
            summary=summary,
            details=details,
            command=command,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
