from pathlib import Path
from typing import cast

import pytest

from module_agent.code.adapters.workspace import LocalCodeWorkspace
from module_agent.code.domain.ports import CodeWorkspace


def test_workspace_returns_stable_repository_path(tmp_path: Path) -> None:
    root = tmp_path / "code-runs"
    workspace: CodeWorkspace = LocalCodeWorkspace(root)

    first = workspace.repository_path(
        literature_run_id=19,
        paper_id=32,
    )
    second = workspace.repository_path(
        literature_run_id=19,
        paper_id=32,
    )

    assert first == (
        root.resolve()
        / "run-19"
        / "paper-32"
        / "repository"
    )
    assert second == first


def test_workspace_does_not_create_directories(tmp_path: Path) -> None:
    root = tmp_path / "code-runs"
    workspace = LocalCodeWorkspace(root)

    destination = workspace.repository_path(1, 2)

    assert not root.exists()
    assert not destination.exists()


@pytest.mark.parametrize(
    ("literature_run_id", "paper_id"),
    [
        (0, 1),
        (-1, 1),
        (True, 1),
        ("1", 1),
        (1, 0),
        (1, -1),
        (1, False),
        (1, "2"),
    ],
)
def test_workspace_rejects_invalid_identifiers(
    tmp_path: Path,
    literature_run_id: object,
    paper_id: object,
) -> None:
    workspace = LocalCodeWorkspace(tmp_path / "code-runs")

    with pytest.raises(ValueError, match="must be a positive integer"):
        workspace.repository_path(
            cast(int, literature_run_id),
            cast(int, paper_id),
        )


def test_workspace_result_stays_inside_resolved_root(tmp_path: Path) -> None:
    root = tmp_path / "parent" / ".." / "code-runs"
    workspace = LocalCodeWorkspace(root)

    destination = workspace.repository_path(3, 4)

    assert destination.is_relative_to(workspace.root)
