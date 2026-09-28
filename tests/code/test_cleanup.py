import os
from pathlib import Path

from module_agent.code.application.cleanup import WorkspaceCleanupService


def test_cleanup_is_dry_run_by_default(tmp_path: Path) -> None:
    run = tmp_path / "run-7"
    run.mkdir()
    os.utime(run, (1, 1))

    report = WorkspaceCleanupService(tmp_path).cleanup(
        retention_days=1,
        now=200_000,
    )

    assert report.candidates == [str(run)]
    assert run.exists()


def test_cleanup_quarantines_before_purge(tmp_path: Path) -> None:
    run = tmp_path / "run-7"
    run.mkdir()
    (run / "artifact.txt").write_text("recoverable")
    os.utime(run, (1, 1))

    report = WorkspaceCleanupService(tmp_path).cleanup(
        retention_days=1,
        trash_retention_days=1,
        dry_run=False,
        now=200_000,
    )

    assert not run.exists()
    assert len(report.quarantined) == 1
    assert Path(report.quarantined[0], "artifact.txt").read_text() == "recoverable"
