"""Bounded dependency installation and project tests in Docker."""

from pathlib import Path

from module_agent.code.domain.artifact import CodeArtifact, CodeArtifactStatus
from module_agent.validation.domain.ports import SandboxRunner
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)
from module_agent.validation.domain.request import ValidationMode, ValidationPolicy
from module_agent.validation.domain.sandbox import SandboxExecutionRequest


class ProjectTestsCheck:
    """Install a Python project into /tmp and optionally run all tests."""

    SCRIPT = """
import pathlib
import subprocess
import sys

root = pathlib.Path('/workspace/repository')
if not any((root / name).exists() for name in ('pyproject.toml', 'setup.py', 'setup.cfg')):
    print('module_agent_skip=no_python_package')
    raise SystemExit(5)

venv = pathlib.Path('/tmp/module-agent-venv')
subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
python = str(venv / 'bin' / 'python')
subprocess.run([
    python, '-m', 'pip', 'install', '--disable-pip-version-check',
    '--no-input', 'pytest', str(root),
], check=True)
print('module_agent_dependencies=installed')
if sys.argv[1] == 'tests':
    raise SystemExit(subprocess.run([
        python, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', str(root),
    ]).returncode)
""".strip()

    def __init__(
        self,
        runner: SandboxRunner,
        policy: ValidationPolicy,
        *,
        run_tests: bool,
    ) -> None:
        if policy.mode is not ValidationMode.SANDBOX:
            raise ValueError("ProjectTestsCheck requires sandbox mode")
        if not policy.allow_network:
            raise ValueError("Dependency installation requires network access")
        self.runner = runner
        self.policy = policy
        self.run_tests = run_tests

    @property
    def kind(self) -> ValidationCheckKind:
        return (
            ValidationCheckKind.PROJECT_TESTS
            if self.run_tests
            else ValidationCheckKind.DEPENDENCY_INSTALL
        )

    def supports(self, artifact: CodeArtifact) -> bool:
        return artifact.status in {
            CodeArtifactStatus.REPOSITORY_READY,
            CodeArtifactStatus.REPRODUCTION_PLANNED,
        }

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        if artifact.local_path is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository artifact has no local path",
            )
        result = await self.runner.execute(
            SandboxExecutionRequest(
                repository_path=Path(artifact.local_path),
                argv=[
                    "python",
                    "-c",
                    self.SCRIPT,
                    "tests" if self.run_tests else "install",
                ],
                policy=self.policy,
                max_output_bytes=262_144,
            )
        )
        details: dict[str, object] = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        }
        if result.exit_code == 5 and "module_agent_skip=" in result.stdout:
            status = ValidationCheckStatus.SKIPPED
            summary = "Repository has no installable Python package"
        elif result.timed_out:
            status = ValidationCheckStatus.FAILED
            summary = "Project validation timed out"
        elif result.exit_code != 0:
            status = ValidationCheckStatus.FAILED
            summary = (
                "Project tests failed"
                if self.run_tests
                else "Dependency installation failed"
            )
        else:
            status = ValidationCheckStatus.PASSED
            summary = (
                "Project tests passed"
                if self.run_tests
                else "Dependencies installed successfully"
            )
        return ValidationCheck(
            kind=self.kind,
            status=status,
            summary=summary,
            details=details,
            command="python -c <isolated-install-and-test>",
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
