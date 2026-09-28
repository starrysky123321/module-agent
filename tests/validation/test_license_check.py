import asyncio
from collections.abc import Sequence
from pathlib import Path

import pytest

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.license import LicenseCheck
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


def make_repository_artifact(
    *,
    license_spdx: str | None = None,
) -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path="/workspace/run-1/paper-1/repository",
        license_spdx=license_spdx,
    )


@pytest.mark.parametrize(
    "filename",
    ["LICENSE", "License.md", "license.TXT", "COPYING"],
)
def test_license_check_accepts_common_names_case_insensitively(
    filename: str,
) -> None:
    inspector = FakeRepositoryFileInspector([filename])
    check = LicenseCheck(inspector)

    result = asyncio.run(
        check.run(make_repository_artifact(license_spdx="MIT"))
    )

    assert result.kind is ValidationCheckKind.LICENSE
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details == {
        "file": filename,
        "license_spdx": "MIT",
        "source": "repository_file",
    }


def test_license_check_accepts_known_spdx_metadata_without_file() -> None:
    check = LicenseCheck(FakeRepositoryFileInspector([]))

    result = asyncio.run(
        check.run(make_repository_artifact(license_spdx=" Apache-2.0 "))
    )

    assert result.status is ValidationCheckStatus.PASSED
    assert result.details == {
        "license_spdx": "Apache-2.0",
        "source": "artifact_metadata",
    }


@pytest.mark.parametrize("license_spdx", [None, "", "  ", "NOASSERTION"])
def test_license_check_warns_when_license_is_unknown(
    license_spdx: str | None,
) -> None:
    check = LicenseCheck(FakeRepositoryFileInspector([]))

    result = asyncio.run(
        check.run(make_repository_artifact(license_spdx=license_spdx))
    )

    assert result.status is ValidationCheckStatus.WARNING


def test_license_check_does_not_inspect_when_path_is_missing() -> None:
    inspector = FakeRepositoryFileInspector(["LICENSE"])
    check = LicenseCheck(inspector)
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
