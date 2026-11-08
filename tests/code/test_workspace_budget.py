import asyncio
from pathlib import Path

import pytest

from module_agent.code.adapters.workspace_budget import (
    LocalWorkspaceBudgetGuard, WorkspaceBudgetExceeded,
)


def sparse_file(path: Path, mb: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as stream:
        stream.truncate(mb * 1024 * 1024)


def test_workspace_budget_cancels_writes_and_counts_all_papers(tmp_path: Path) -> None:
    async def run() -> None:
        cancelled = asyncio.Event()

        async def operation():
            try:
                sparse_file(tmp_path / "run-7/paper-1/.clone-test/repository/weights.bin", 65)
                sparse_file(tmp_path / "run-7/paper-2/reproduction/data.bin", 65)
                await asyncio.Future()
            finally:
                cancelled.set()
            return []

        guard = LocalWorkspaceBudgetGuard(tmp_path, poll_seconds=0.01)
        with pytest.raises(WorkspaceBudgetExceeded, match="budget"):
            await guard.run(7, 128, operation)
        assert cancelled.is_set()

    asyncio.run(run())


def test_existing_over_budget_workspace_prevents_operation(tmp_path: Path) -> None:
    sparse_file(tmp_path / "run-7/leftover.bin", 129)
    called = False

    async def operation():
        nonlocal called
        called = True
        return []

    with pytest.raises(WorkspaceBudgetExceeded):
        asyncio.run(LocalWorkspaceBudgetGuard(tmp_path).run(7, 128, operation))
    assert not called
    assert (tmp_path / "run-7/leftover.bin").exists()


def test_workspace_budget_does_not_follow_symlinks_or_delete_other_tasks(tmp_path: Path) -> None:
    sparse_file(tmp_path / "other-task/large.bin", 256)
    (tmp_path / "run-7").mkdir()
    (tmp_path / "run-7/link").symlink_to(tmp_path / "other-task", target_is_directory=True)

    async def operation():
        sparse_file(tmp_path / "run-7/small.bin", 1)
        return []

    assert asyncio.run(LocalWorkspaceBudgetGuard(tmp_path).run(7, 128, operation)) == []
    assert (tmp_path / "other-task/large.bin").exists()


def test_workspace_budget_rejects_task_root_symlink_escape(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "run-7").symlink_to(outside, target_is_directory=True)

    async def operation():
        raise AssertionError("Must not run outside workspace")

    with pytest.raises(ValueError, match="escapes"):
        asyncio.run(LocalWorkspaceBudgetGuard(root).run(7, 128, operation))
