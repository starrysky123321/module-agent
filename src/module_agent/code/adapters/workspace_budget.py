"""Monitor all artifacts of a task; this is not a filesystem hard quota."""

import asyncio
from collections.abc import Awaitable, Callable
import os
from pathlib import Path
import shutil
import stat

from module_agent.code.domain.artifact import CodeArtifact


class WorkspaceBudgetExceeded(ValueError):
    """The task cannot continue under its requested storage budget."""


class LocalWorkspaceBudgetGuard:
    def __init__(self, root: Path, *, poll_seconds: float = 0.25) -> None:
        self.root = root.resolve()
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.poll_seconds = poll_seconds

    def _usage(self, run_path: Path) -> int:
        """Count apparent file sizes including temporary clones, without symlinks."""
        pending = [run_path]
        total = 0
        entries = 0
        while pending:
            directory = pending.pop()
            try:
                with os.scandir(directory) as children:
                    for entry in children:
                        entries += 1
                        if entries > 200_000:
                            raise WorkspaceBudgetExceeded("Workspace file-count inspection limit exceeded")
                        try:
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode):
                                pending.append(Path(entry.path))
                            elif stat.S_ISREG(info.st_mode):
                                total += info.st_size
                        except FileNotFoundError:
                            continue
            except FileNotFoundError:
                continue
        return total

    def _check(self, run_path: Path, limit_bytes: int) -> None:
        if not run_path.resolve().is_relative_to(self.root):
            raise ValueError("Task workspace escapes allowed root")
        usage = self._usage(run_path)
        if usage > limit_bytes:
            raise WorkspaceBudgetExceeded(
                f"Task workspace uses {usage} bytes; budget is {limit_bytes} bytes"
            )

    async def run(
        self,
        literature_run_id: int,
        limit_mb: int,
        operation: Callable[[], Awaitable[list[CodeArtifact]]],
    ) -> list[CodeArtifact]:
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError("literature_run_id must be a positive integer")
        if type(limit_mb) is not int or limit_mb <= 0:
            raise ValueError("Workspace limit must be a positive integer")
        run_path = self.root / f"run-{literature_run_id}"
        limit_bytes = limit_mb * 1024 * 1024
        await asyncio.to_thread(self._check, run_path, limit_bytes)
        disk_path = self.root
        while not disk_path.exists() and disk_path != disk_path.parent:
            disk_path = disk_path.parent
        free = await asyncio.to_thread(shutil.disk_usage, disk_path)
        if free.free < limit_bytes:
            raise WorkspaceBudgetExceeded("Insufficient free disk space for the requested task budget")
        task = asyncio.ensure_future(operation())
        try:
            while not task.done():
                await asyncio.wait({task}, timeout=self.poll_seconds)
                await asyncio.to_thread(self._check, run_path, limit_bytes)
            await asyncio.to_thread(self._check, run_path, limit_bytes)
            return await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
