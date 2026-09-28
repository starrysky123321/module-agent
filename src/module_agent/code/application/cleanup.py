"""Safe, two-phase cleanup for Code Agent workspaces."""

import os
import re
import shutil
import time
from pathlib import Path

from pydantic import BaseModel, Field


_RUN_DIRECTORY = re.compile(r"^run-[1-9][0-9]*$")


class WorkspaceCleanupReport(BaseModel):
    """Paths selected, quarantined, purged, or skipped by cleanup."""

    dry_run: bool
    candidates: list[str] = Field(default_factory=list)
    quarantined: list[str] = Field(default_factory=list)
    purged: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)


class WorkspaceCleanupService:
    """Quarantine stale run directories before permanently purging them."""

    def __init__(self, workspace_root: Path) -> None:
        root = workspace_root.resolve()
        if root == Path(root.anchor) or root == Path.home().resolve():
            raise ValueError("Workspace cleanup root is too broad")
        self.workspace_root = root
        self.trash_root = root / ".trash"

    def cleanup(
        self,
        *,
        retention_days: int,
        trash_retention_days: int = 7,
        dry_run: bool = True,
        now: float | None = None,
    ) -> WorkspaceCleanupReport:
        """Quarantine old run directories and purge expired quarantine."""
        if retention_days < 1 or trash_retention_days < 1:
            raise ValueError("Retention periods must be positive")
        current_time = time.time() if now is None else now
        stale_before = current_time - retention_days * 86400
        purge_before = current_time - trash_retention_days * 86400
        report = WorkspaceCleanupReport(dry_run=dry_run)

        if not self.workspace_root.exists():
            return report
        if not self.workspace_root.is_dir() or self.workspace_root.is_symlink():
            raise ValueError("Workspace root must be a real directory")

        for entry in sorted(self.workspace_root.iterdir()):
            if entry.name == self.trash_root.name:
                continue
            if not _RUN_DIRECTORY.fullmatch(entry.name):
                report.skipped.append(str(entry))
                continue
            if entry.is_symlink() or not entry.is_dir():
                report.skipped.append(str(entry))
                continue
            if entry.stat(follow_symlinks=False).st_mtime > stale_before:
                continue
            report.candidates.append(str(entry))
            if dry_run:
                continue
            self.trash_root.mkdir(mode=0o700, exist_ok=True)
            destination = self.trash_root / (
                f"{entry.name}-{int(current_time)}-{os.getpid()}"
            )
            os.replace(entry, destination)
            os.utime(destination, (current_time, current_time))
            report.quarantined.append(str(destination))

        if self.trash_root.is_dir() and not self.trash_root.is_symlink():
            for entry in sorted(self.trash_root.iterdir()):
                if entry.is_symlink() or not entry.is_dir():
                    report.skipped.append(str(entry))
                    continue
                if entry.stat(follow_symlinks=False).st_mtime > purge_before:
                    continue
                if dry_run:
                    report.purged.append(str(entry))
                    continue
                shutil.rmtree(entry)
                report.purged.append(str(entry))
        return report
