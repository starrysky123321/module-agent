from collections.abc import Sequence

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.validation.domain.ports import StaticCheck
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)


class StaticValidator:
    """Run read-only checks without importing or executing artifact code."""

    def __init__(self, checks: Sequence[StaticCheck]) -> None:
        """初始化当前对象。"""
        if not checks:
            raise ValueError("StaticValidator requires at least one check")

        self.checks = tuple(checks)

    async def validate(self, artifact: CodeArtifact) -> list[ValidationCheck]:
        """校验输入和业务约束。"""
        results: list[ValidationCheck] = []

        for check in self.checks:
            try:
                if not check.supports(artifact):
                    continue

                result = await check.run(artifact)
                if result.kind is not check.kind:
                    raise ValueError(
                        "Static check returned a different check kind"
                    )
                results.append(result)
            except Exception as exc:
                results.append(self._failure(check.kind, exc))

        if results:
            return results

        return [
            ValidationCheck(
                kind=ValidationCheckKind.ARTIFACT_CONTRACT,
                status=ValidationCheckStatus.SKIPPED,
                summary="No static checks apply to this artifact",
            )
        ]

    @staticmethod
    def _failure(
        kind: ValidationCheckKind,
        exc: Exception,
    ) -> ValidationCheck:
        message = str(exc).strip() or type(exc).__name__
        return ValidationCheck(
            kind=kind,
            status=ValidationCheckStatus.FAILED,
            summary=f"Static check failed: {message}",
            details={"error_type": type(exc).__name__},
        )
