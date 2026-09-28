"""Quarantine and purge stale Code Agent workspaces."""

import argparse

from module_agent.code.application.cleanup import WorkspaceCleanupService
from module_agent.shared.config import app_settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--trash-retention-days", type=int, default=7)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply cleanup; without this flag the command is a dry run.",
    )
    args = parser.parse_args()
    report = WorkspaceCleanupService(
        app_settings.code_workspace_root
    ).cleanup(
        retention_days=args.retention_days,
        trash_retention_days=args.trash_retention_days,
        dry_run=not args.execute,
    )
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
