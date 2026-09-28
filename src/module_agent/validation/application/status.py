from collections.abc import Sequence

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckStatus,
    ValidationStatus,
)


class ValidationStatusResolver:
    """Resolve one stable report status from an artifact and its checks."""

    def resolve(
        self,
        artifact: CodeArtifact,
        checks: Sequence[ValidationCheck],
    ) -> ValidationStatus:
        """解析并返回匹配结果。"""
        if not checks:
            raise ValueError(
                "Validation status requires at least one check"
            )

        if artifact.status is CodeArtifactStatus.FAILED:
            return ValidationStatus.FAILED

        check_statuses = {check.status for check in checks}

        if ValidationCheckStatus.FAILED in check_statuses:
            return ValidationStatus.FAILED

        if artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED:
            return ValidationStatus.PARTIAL

        if check_statuses.intersection(
            {
                ValidationCheckStatus.WARNING,
                ValidationCheckStatus.SKIPPED,
            }
        ):
            return ValidationStatus.PARTIAL

        return ValidationStatus.PASSED
