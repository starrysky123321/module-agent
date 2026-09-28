import asyncio
from collections.abc import Sequence

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.python_import import (
    PythonImportCheck,
)
from module_agent.validation.application.checks.python_syntax import (
    PythonSyntaxCheck,
)
from module_agent.validation.application.checks.smoke_test import (
    SmokeTestCheck,
)
from module_agent.validation.application.checks.project_tests import (
    ProjectTestsCheck,
)
from module_agent.validation.application.static_validator import (
    StaticValidator,
)
from module_agent.validation.application.status import (
    ValidationStatusResolver,
)
from module_agent.validation.domain.ports import SandboxRunner, StaticCheck
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationReport,
)
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationRequest,
)


class ValidationAgent:
    """Validate artifacts independently and return one report per paper."""

    def __init__(
        self,
        static_validator: StaticValidator,
        *,
        status_resolver: ValidationStatusResolver | None = None,
        sandbox_runner: SandboxRunner | None = None,
    ) -> None:
        """初始化当前对象。"""
        self.static_validator = static_validator
        self.status_resolver = status_resolver or ValidationStatusResolver()
        self.sandbox_runner = sandbox_runner

    async def run(
        self,
        request: ValidationRequest,
    ) -> list[ValidationReport]:
        """执行当前任务。"""
        return list(
            await asyncio.gather(
                *(
                    self._validate_artifact(request, artifact)
                    for artifact in request.artifacts
                )
            )
        )

    async def _validate_artifact(
        self,
        request: ValidationRequest,
        artifact: CodeArtifact,
    ) -> ValidationReport:
        try:
            checks = await self.static_validator.validate(artifact)
        except Exception as exc:
            return self._failure_report(request, artifact, exc)

        try:
            sandbox_checks, code_executed = await self._run_sandbox_checks(
                request,
                artifact,
            )
            checks.extend(sandbox_checks)
            return self._build_report(
                request,
                artifact,
                checks,
                code_executed=code_executed,
            )
        except Exception as exc:
            message = str(exc).strip() or type(exc).__name__
            checks.append(
                ValidationCheck(
                    kind=ValidationCheckKind.ARTIFACT_CONTRACT,
                    status=ValidationCheckStatus.FAILED,
                    summary=f"Artifact validation failed: {message}",
                    details={"error_type": type(exc).__name__},
                )
            )
            return self._build_report(
                request,
                artifact,
                checks,
                code_executed=False,
                error=message,
            )

    def _failure_report(
        self,
        request: ValidationRequest,
        artifact: CodeArtifact,
        exc: Exception,
    ) -> ValidationReport:
        message = str(exc).strip() or type(exc).__name__
        check = ValidationCheck(
            kind=ValidationCheckKind.ARTIFACT_CONTRACT,
            status=ValidationCheckStatus.FAILED,
            summary=f"Artifact validation failed: {message}",
            details={"error_type": type(exc).__name__},
        )
        return self._build_report(
            request,
            artifact,
            [check],
            code_executed=False,
            error=message,
        )

    async def _run_sandbox_checks(
        self,
        request: ValidationRequest,
        artifact: CodeArtifact,
    ) -> tuple[list[ValidationCheck], bool]:
        if (
            request.policy.mode is ValidationMode.STATIC
            or artifact.status not in {
                CodeArtifactStatus.REPOSITORY_READY,
                CodeArtifactStatus.REPRODUCTION_PLANNED,
            }
            or artifact.local_path is None
        ):
            return [], False

        if self.sandbox_runner is None:
            raise RuntimeError(
                "Sandbox validation was requested but no sandbox runner "
                "is configured"
            )

        checks: list[StaticCheck] = [
            PythonSyntaxCheck(self.sandbox_runner, request.policy),
        ]
        options = request.sandbox_options
        code_executed = False

        if options is not None and options.import_modules:
            checks.append(
                PythonImportCheck(
                    self.sandbox_runner,
                    request.policy,
                    options.import_modules,
                )
            )
            code_executed = True

        if options is not None and options.smoke_test_argv is not None:
            checks.append(
                SmokeTestCheck(
                    self.sandbox_runner,
                    request.policy,
                    options.smoke_test_argv,
                    working_directory=(
                        options.smoke_test_working_directory
                    ),
                )
            )
            code_executed = True

        if options is not None and options.install_dependencies:
            checks.append(
                ProjectTestsCheck(
                    self.sandbox_runner,
                    request.policy,
                    run_tests=options.run_project_tests,
                )
            )
            code_executed = True

        return await StaticValidator(checks).validate(artifact), code_executed

    def _build_report(
        self,
        request: ValidationRequest,
        artifact: CodeArtifact,
        checks: Sequence[ValidationCheck],
        *,
        code_executed: bool,
        error: str | None = None,
    ) -> ValidationReport:
        warnings = list(artifact.warnings)
        warnings.extend(
            check.summary
            for check in checks
            if check.status
            in {
                ValidationCheckStatus.WARNING,
                ValidationCheckStatus.SKIPPED,
            }
        )
        warnings.extend(
            f"Output was truncated for {check.kind.value}"
            for check in checks
            if check.details.get("output_truncated") is True
        )

        return ValidationReport(
            literature_run_id=request.literature_run_id,
            paper_id=artifact.paper_id,
            artifact_origin=artifact.origin,
            artifact_status=artifact.status,
            mode=request.policy.mode,
            status=self.status_resolver.resolve(artifact, checks),
            checks=list(checks),
            code_executed=code_executed,
            warnings=list(dict.fromkeys(warnings)),
            error=error or artifact.error,
        )
