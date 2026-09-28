import asyncio
from pathlib import Path
import shutil
import subprocess

import pytest

from module_agent.validation.adapters.git import LocalGitInspector
from module_agent.validation.domain.ports import GitInspector


GIT_AVAILABLE = shutil.which("git") is not None


def _run_git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_git_repository(path: Path) -> str:
    path.mkdir(parents=True)
    _run_git(path, "init")
    (path / "README.md").write_text("example\n", encoding="utf-8")
    _run_git(path, "add", "README.md")
    _run_git(
        path,
        "-c",
        "user.name=Validation Test",
        "-c",
        "user.email=validation@example.com",
        "commit",
        "-m",
        "Initial commit",
    )
    return _run_git(path, "rev-parse", "HEAD")


def test_local_git_inspector_satisfies_port(tmp_path: Path) -> None:
    inspector: GitInspector = LocalGitInspector(tmp_path)

    assert isinstance(inspector, LocalGitInspector)


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is not installed")
def test_local_git_inspector_reads_repository_head(tmp_path: Path) -> None:
    allowed_root = tmp_path / "workspaces"
    repository = allowed_root / "repository"
    expected_commit = _create_git_repository(repository)
    inspector = LocalGitInspector(allowed_root)

    actual_commit = asyncio.run(inspector.head_commit(repository))

    assert actual_commit == expected_commit


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git is not installed")
def test_local_git_inspector_returns_none_for_non_git_directory(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    directory = allowed_root / "not-a-repository"
    directory.mkdir(parents=True)
    inspector = LocalGitInspector(allowed_root)

    assert asyncio.run(inspector.head_commit(directory)) is None


def test_local_git_inspector_rejects_path_outside_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    inspector = LocalGitInspector(allowed_root)

    assert asyncio.run(inspector.head_commit(outside_directory)) is None


def test_local_git_inspector_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    escaping_link = allowed_root / "repository-link"
    escaping_link.symlink_to(outside_directory, target_is_directory=True)
    inspector = LocalGitInspector(allowed_root)

    assert asyncio.run(inspector.head_commit(escaping_link)) is None


@pytest.mark.parametrize("git_executable", ["", "   "])
def test_local_git_inspector_rejects_blank_executable(
    tmp_path: Path,
    git_executable: str,
) -> None:
    with pytest.raises(ValueError, match="git_executable"):
        LocalGitInspector(tmp_path, git_executable=git_executable)


def test_local_git_inspector_normalizes_executable(tmp_path: Path) -> None:
    inspector = LocalGitInspector(tmp_path, git_executable="  git  ")

    assert inspector.git_executable == "git"


@pytest.mark.parametrize("timeout_seconds", [0, -1.0])
def test_local_git_inspector_rejects_non_positive_timeout(
    tmp_path: Path,
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        LocalGitInspector(tmp_path, timeout_seconds=timeout_seconds)
