import asyncio

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.static_validator import StaticValidator
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)


def _failed_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Repository preparation failed",
    )


class RecordingCheck:
    def __init__(
        self,
        *,
        kind: ValidationCheckKind,
        status: ValidationCheckStatus = ValidationCheckStatus.PASSED,
        supported: bool = True,
    ) -> None:
        self._kind = kind
        self.status = status
        self.supported = supported
        self.calls: list[CodeArtifact] = []

    @property
    def kind(self) -> ValidationCheckKind:
        return self._kind

    def supports(self, artifact: CodeArtifact) -> bool:
        return self.supported

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        self.calls.append(artifact)
        return ValidationCheck(
            kind=self.kind,
            status=self.status,
            summary=f"Checked {self.kind}",
        )


class RaisingCheck(RecordingCheck):
    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        raise RuntimeError("Unreadable workspace")


class WrongKindCheck(RecordingCheck):
    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        return ValidationCheck(
            kind=ValidationCheckKind.README,
            status=ValidationCheckStatus.PASSED,
            summary="Wrong result kind",
        )


def test_validator_requires_at_least_one_check() -> None:
    with pytest.raises(ValueError, match="at least one check"):
        StaticValidator([])


def test_validator_runs_supported_checks_in_registration_order() -> None:
    artifact = _failed_artifact()
    first = RecordingCheck(kind=ValidationCheckKind.ARTIFACT_CONTRACT)
    second = RecordingCheck(kind=ValidationCheckKind.SECURITY_SCAN)

    results = asyncio.run(
        StaticValidator([first, second]).validate(artifact)
    )

    assert [result.kind for result in results] == [
        ValidationCheckKind.ARTIFACT_CONTRACT,
        ValidationCheckKind.SECURITY_SCAN,
    ]
    assert first.calls == [artifact]
    assert second.calls == [artifact]


def test_validator_does_not_run_unsupported_check() -> None:
    check = RecordingCheck(
        kind=ValidationCheckKind.WORKSPACE,
        supported=False,
    )

    results = asyncio.run(
        StaticValidator([check]).validate(_failed_artifact())
    )

    assert check.calls == []
    assert len(results) == 1
    assert results[0].kind is ValidationCheckKind.ARTIFACT_CONTRACT
    assert results[0].status is ValidationCheckStatus.SKIPPED


def test_validator_converts_one_check_exception_to_failed_result() -> None:
    failing = RaisingCheck(kind=ValidationCheckKind.WORKSPACE)
    succeeding = RecordingCheck(kind=ValidationCheckKind.SECURITY_SCAN)

    results = asyncio.run(
        StaticValidator([failing, succeeding]).validate(_failed_artifact())
    )

    assert results[0].kind is ValidationCheckKind.WORKSPACE
    assert results[0].status is ValidationCheckStatus.FAILED
    assert results[0].details == {"error_type": "RuntimeError"}
    assert results[1].status is ValidationCheckStatus.PASSED


def test_validator_rejects_result_from_a_different_check_kind() -> None:
    check = WrongKindCheck(kind=ValidationCheckKind.WORKSPACE)

    results = asyncio.run(
        StaticValidator([check]).validate(_failed_artifact())
    )

    assert results[0].kind is ValidationCheckKind.WORKSPACE
    assert results[0].status is ValidationCheckStatus.FAILED
    assert results[0].details == {"error_type": "ValueError"}
