import asyncio
from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.workspace import WorkspaceCheck
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
)


class FakeWorkspaceInspector:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[Path] = []

    def is_directory(self, path: Path) -> bool:
        self.calls.append(path)
        return self.result


def make_repository_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path="/workspace/run-1/paper-1/repository",
    )


def test_workspace_check_supports_only_ready_repository() -> None:
    check = WorkspaceCheck(FakeWorkspaceInspector(True))
    failed_artifact = CodeArtifact(
        paper_id=2,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Repository preparation failed",
    )

    assert check.supports(make_repository_artifact()) is True
    assert check.supports(failed_artifact) is False


def test_workspace_check_passes_when_directory_exists() -> None:
    inspector = FakeWorkspaceInspector(True)
    check = WorkspaceCheck(inspector)

    result = asyncio.run(check.run(make_repository_artifact()))

    expected_path = Path("/workspace/run-1/paper-1/repository")
    assert inspector.calls == [expected_path]
    assert result.kind is ValidationCheckKind.WORKSPACE
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details == {"path": str(expected_path)}


def test_workspace_check_fails_when_directory_does_not_exist() -> None:
    inspector = FakeWorkspaceInspector(False)
    check = WorkspaceCheck(inspector)

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.kind is ValidationCheckKind.WORKSPACE
    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Repository workspace does not exist"


def test_workspace_check_fails_without_calling_inspector_when_path_missing(
) -> None:
    inspector = FakeWorkspaceInspector(True)
    check = WorkspaceCheck(inspector)
    # model_construct intentionally bypasses CodeArtifact's domain validation
    # so this defensive branch can be tested directly.
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Repository artifact has no local path"
