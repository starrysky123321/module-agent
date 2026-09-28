import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from module_agent.code.adapters.git import (
    GitCommandError,
    GitRepositoryFetcher,
)
from module_agent.code.domain.repository import RepositoryCandidate


def make_candidate(
    repository_url: str = "https://github.com/alice/example",
) -> RepositoryCandidate:
    return RepositoryCandidate(
        full_name="alice/example",
        repository_url=repository_url,
        owner_login="alice",
    )


@pytest.mark.parametrize(
    ("git_executable", "timeout_seconds"),
    [
        ("", 1.0),
        ("   ", 1.0),
        (sys.executable, 0),
        (sys.executable, -1),
    ],
)
def test_git_runner_rejects_invalid_configuration(
    git_executable: str,
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        GitRepositoryFetcher(
            git_executable=git_executable,
            timeout_seconds=timeout_seconds,
        )


def test_git_runner_returns_stripped_stdout(tmp_path: Path) -> None:
    fetcher = GitRepositoryFetcher(git_executable=sys.executable)

    output = asyncio.run(
        fetcher._run_git(
            "-c",
            "from pathlib import Path; print(Path.cwd()); print('ok')",
            cwd=tmp_path,
        )
    )

    assert output == f"{tmp_path}\nok"


def test_git_runner_raises_stderr_for_failed_command() -> None:
    fetcher = GitRepositoryFetcher(git_executable=sys.executable)

    with pytest.raises(GitCommandError, match="expected failure"):
        asyncio.run(
            fetcher._run_git(
                "-c",
                "import sys; print('expected failure', file=sys.stderr); sys.exit(7)",
            )
        )


def test_git_runner_falls_back_to_exit_code_without_stderr() -> None:
    fetcher = GitRepositoryFetcher(git_executable=sys.executable)

    with pytest.raises(GitCommandError, match="Git exited with code 9"):
        asyncio.run(
            fetcher._run_git(
                "-c",
                "import sys; sys.exit(9)",
            )
        )


def test_git_runner_replaces_invalid_utf8_output() -> None:
    fetcher = GitRepositoryFetcher(git_executable=sys.executable)

    output = asyncio.run(
        fetcher._run_git(
            "-c",
            "import sys; sys.stdout.buffer.write(b'valid\\xffoutput')",
        )
    )

    assert output == "valid�output"


def test_git_runner_kills_process_after_timeout() -> None:
    fetcher = GitRepositoryFetcher(
        git_executable=sys.executable,
        timeout_seconds=0.05,
    )

    with pytest.raises(GitCommandError, match="timed out after 0.05 seconds"):
        asyncio.run(
            fetcher._run_git(
                "-c",
                "import time; time.sleep(10)",
            )
        )


def test_fetch_validation_returns_resolved_absolute_destination(
    tmp_path: Path,
) -> None:
    fetcher = GitRepositoryFetcher()
    destination = tmp_path / "parent" / ".." / "repository"

    result = fetcher._validate_fetch_request(
        make_candidate(),
        destination,
    )

    assert result == destination.resolve()


def test_fetch_validation_rejects_non_https_repository(
    tmp_path: Path,
) -> None:
    fetcher = GitRepositoryFetcher()

    with pytest.raises(ValueError, match="HTTPS"):
        fetcher._validate_fetch_request(
            make_candidate("http://github.com/alice/example"),
            tmp_path / "repository",
        )


def test_fetch_validation_rejects_relative_destination() -> None:
    fetcher = GitRepositoryFetcher()

    with pytest.raises(ValueError, match="absolute"):
        fetcher._validate_fetch_request(
            make_candidate(),
            Path("relative/repository"),
        )


@pytest.mark.parametrize("existing_kind", ["file", "directory"])
def test_fetch_validation_rejects_existing_destination(
    tmp_path: Path,
    existing_kind: str,
) -> None:
    destination = tmp_path / "repository"
    if existing_kind == "file":
        destination.touch()
    else:
        destination.mkdir()

    fetcher = GitRepositoryFetcher()

    with pytest.raises(FileExistsError, match="already exists"):
        fetcher._validate_fetch_request(
            make_candidate(),
            destination,
        )


def test_fetch_clones_to_temporary_directory_then_publishes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = GitRepositoryFetcher()
    destination = tmp_path / "run-1" / "paper-2" / "repository"
    commit_sha = "a" * 40
    calls: list[tuple[str, ...]] = []

    async def fake_run_git(*args: str, cwd: Path | None = None) -> str:
        assert cwd is None
        calls.append(args)
        if "clone" in args:
            temporary_repository = Path(args[-1])
            temporary_repository.mkdir(parents=True)
            (temporary_repository / "README.md").write_text("example")
            return ""
        return commit_sha

    monkeypatch.setattr(fetcher, "_run_git", fake_run_git)

    checkout = asyncio.run(fetcher.fetch(make_candidate(), destination))

    assert checkout.repository_url == make_candidate().repository_url
    assert checkout.commit_sha == commit_sha
    assert checkout.local_path == str(destination)
    assert (destination / "README.md").read_text() == "example"
    assert calls[0][0:4] == (
        "-c",
        "protocol.file.allow=never",
        "-c",
        "core.hooksPath=/dev/null",
    )
    assert calls[0][4:10] == (
        "clone",
        "--depth",
        "1",
        "--filter=blob:none",
        "--no-tags",
        "--single-branch",
    )
    assert calls[1] == (
        "-C",
        calls[0][-1],
        "rev-parse",
        "HEAD",
    )
    assert list(destination.parent.glob(".clone-*")) == []


def test_fetch_cleans_temporary_directory_when_clone_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = GitRepositoryFetcher()
    destination = tmp_path / "run-1" / "repository"
    run_git = AsyncMock(side_effect=GitCommandError("clone failed"))
    monkeypatch.setattr(fetcher, "_run_git", run_git)

    with pytest.raises(GitCommandError, match="clone failed"):
        asyncio.run(fetcher.fetch(make_candidate(), destination))

    assert not destination.exists()
    assert list(destination.parent.glob(".clone-*")) == []


def test_fetch_does_not_overwrite_destination_created_during_clone(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = GitRepositoryFetcher()
    destination = tmp_path / "run-1" / "repository"

    async def fake_run_git(*args: str, cwd: Path | None = None) -> str:
        if "clone" in args:
            Path(args[-1]).mkdir(parents=True)
            destination.mkdir()
            (destination / "owner.txt").write_text("other process")
            return ""
        return "b" * 40

    monkeypatch.setattr(fetcher, "_run_git", fake_run_git)

    with pytest.raises(FileExistsError, match="already exists"):
        asyncio.run(fetcher.fetch(make_candidate(), destination))

    assert (destination / "owner.txt").read_text() == "other process"
    assert list(destination.parent.glob(".clone-*")) == []
