import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.dependency_manifest import (
    DependencyManifestCheck,
)
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


@pytest.mark.parametrize(
    "filename",
    [
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "Cargo.toml",
        "go.mod",
        "pom.xml",
        "CMakeLists.txt",
    ],
)
def test_dependency_check_accepts_common_manifests(filename: str) -> None:
    check = DependencyManifestCheck(FakeRepositoryFileInspector([filename]))

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.kind is ValidationCheckKind.DEPENDENCY_MANIFEST
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details == {"files": [filename]}


def test_dependency_check_accepts_requirements_variant() -> None:
    check = DependencyManifestCheck(
        FakeRepositoryFileInspector(["requirements-dev.txt"])
    )

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.status is ValidationCheckStatus.PASSED


def test_dependency_check_returns_all_manifests_in_stable_order() -> None:
    check = DependencyManifestCheck(
        FakeRepositoryFileInspector(
            ["requirements.txt", "README.md", "pyproject.toml"]
        )
    )

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.details == {
        "files": ["pyproject.toml", "requirements.txt"]
    }


def test_dependency_check_warns_when_manifest_is_missing() -> None:
    check = DependencyManifestCheck(
        FakeRepositoryFileInspector(["README.md", "LICENSE"])
    )

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.status is ValidationCheckStatus.WARNING


def test_dependency_check_does_not_inspect_when_path_is_missing() -> None:
    inspector = FakeRepositoryFileInspector(["pyproject.toml"])
    check = DependencyManifestCheck(inspector)
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
