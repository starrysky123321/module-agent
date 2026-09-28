import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.readme import ReadmeCheck
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
)


class FakeRepositoryFileInspector:
    def __init__(self, files: Sequence[str]) -> None:
        self.files = tuple(files)
        self.calls: list[Path] = []

    def list_root_files(self, repository: Path) -> Sequence[str]:
        self.calls.append(repository)
        return self.files


def make_repository_artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path="/workspace/run-1/paper-1/repository",
    )


def test_readme_check_supports_only_ready_repository() -> None:
    check = ReadmeCheck(FakeRepositoryFileInspector([]))
    failed_artifact = CodeArtifact(
        paper_id=2,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Repository preparation failed",
    )

    assert check.supports(make_repository_artifact()) is True
    assert check.supports(failed_artifact) is False


@pytest.mark.parametrize(
    "filename",
    ["README", "README.md", "readme.RST", "ReadMe.TxT"],
)
def test_readme_check_accepts_supported_names_case_insensitively(
    filename: str,
) -> None:
    inspector = FakeRepositoryFileInspector(["src", filename, "pyproject.toml"])
    check = ReadmeCheck(inspector)

    result = asyncio.run(check.run(make_repository_artifact()))

    expected_path = Path("/workspace/run-1/paper-1/repository")
    assert inspector.calls == [expected_path]
    assert result.kind is ValidationCheckKind.README
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details == {"file": filename}


def test_readme_check_warns_when_readme_is_missing() -> None:
    inspector = FakeRepositoryFileInspector(["src", "pyproject.toml"])
    check = ReadmeCheck(inspector)

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.kind is ValidationCheckKind.README
    assert result.status is ValidationCheckStatus.WARNING
    assert result.details == {}


def test_readme_check_does_not_inspect_when_path_is_missing() -> None:
    inspector = FakeRepositoryFileInspector(["README.md"])
    check = ReadmeCheck(inspector)
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
