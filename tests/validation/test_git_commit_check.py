import asyncio
from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.application.checks.git_commit import GitCommitCheck
from module_agent.validation.domain.report import (
    ValidationCheckKind,
    ValidationCheckStatus,
)


class FakeGitInspector:
    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls: list[Path] = []

    async def head_commit(self, path: Path) -> str | None:
        self.calls.append(path)
        return self.result


def make_repository_artifact(
    *,
    commit_sha: str = "abcdef1",
) -> CodeArtifact:
    return CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha=commit_sha,
        local_path="/workspace/run-1/paper-1/repository",
    )


def test_git_commit_check_supports_only_ready_repository() -> None:
    check = GitCommitCheck(FakeGitInspector("a" * 40))
    failed_artifact = CodeArtifact(
        paper_id=2,
        origin=CodeArtifactOrigin.UNKNOWN,
        status=CodeArtifactStatus.FAILED,
        error="Repository preparation failed",
    )

    assert check.supports(make_repository_artifact()) is True
    assert check.supports(failed_artifact) is False


def test_git_commit_check_accepts_case_insensitive_short_sha() -> None:
    inspector = FakeGitInspector(f"  {'abcdef1' + '2' * 33}\n")
    check = GitCommitCheck(inspector)

    result = asyncio.run(
        check.run(make_repository_artifact(commit_sha="ABCDEF1"))
    )

    expected_path = Path("/workspace/run-1/paper-1/repository")
    assert inspector.calls == [expected_path]
    assert result.kind is ValidationCheckKind.GIT_COMMIT
    assert result.status is ValidationCheckStatus.PASSED
    assert result.details["expected_commit"] == "abcdef1"
    assert result.details["actual_commit"] == "abcdef1" + "2" * 33


def test_git_commit_check_reports_commit_mismatch() -> None:
    actual_commit = "b" * 40
    inspector = FakeGitInspector(actual_commit)
    check = GitCommitCheck(inspector)

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.details == {
        "path": "/workspace/run-1/paper-1/repository",
        "expected_commit": "abcdef1",
        "actual_commit": actual_commit,
    }


def test_git_commit_check_fails_when_head_cannot_be_read() -> None:
    check = GitCommitCheck(FakeGitInspector(None))

    result = asyncio.run(check.run(make_repository_artifact()))

    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Unable to read repository HEAD commit"


def test_git_commit_check_does_not_inspect_when_path_is_missing() -> None:
    inspector = FakeGitInspector("a" * 40)
    check = GitCommitCheck(inspector)
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path=None,
        commit_sha="abcdef1",
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Repository artifact has no local path"


def test_git_commit_check_does_not_inspect_when_commit_is_missing() -> None:
    inspector = FakeGitInspector("a" * 40)
    check = GitCommitCheck(inspector)
    malformed_artifact = CodeArtifact.model_construct(
        paper_id=1,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        local_path="/workspace/repository",
        commit_sha=None,
    )

    result = asyncio.run(check.run(malformed_artifact))

    assert inspector.calls == []
    assert result.status is ValidationCheckStatus.FAILED
    assert result.summary == "Repository artifact has no commit SHA"
