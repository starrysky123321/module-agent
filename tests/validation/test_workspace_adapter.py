from pathlib import Path

from module_agent.validation.adapters.workspace import LocalWorkspaceInspector
from module_agent.validation.domain.ports import WorkspaceInspector


def test_local_workspace_inspector_satisfies_port(tmp_path: Path) -> None:
    inspector: WorkspaceInspector = LocalWorkspaceInspector(tmp_path)

    assert isinstance(inspector, LocalWorkspaceInspector)


def test_local_workspace_inspector_accepts_directory_inside_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    repository = allowed_root / "run-1" / "paper-1" / "repository"
    repository.mkdir(parents=True)
    inspector = LocalWorkspaceInspector(allowed_root)

    assert inspector.is_directory(repository) is True


def test_local_workspace_inspector_rejects_file_inside_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    file_path = allowed_root / "README.md"
    file_path.write_text("example", encoding="utf-8")
    inspector = LocalWorkspaceInspector(allowed_root)

    assert inspector.is_directory(file_path) is False


def test_local_workspace_inspector_rejects_missing_path(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    inspector = LocalWorkspaceInspector(allowed_root)

    assert inspector.is_directory(allowed_root / "missing") is False


def test_local_workspace_inspector_rejects_path_outside_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    inspector = LocalWorkspaceInspector(allowed_root)

    traversal_path = allowed_root / ".." / "outside"
    assert inspector.is_directory(traversal_path) is False


def test_local_workspace_inspector_rejects_symlink_escape(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    escaping_link = allowed_root / "repository-link"
    escaping_link.symlink_to(outside_directory, target_is_directory=True)
    inspector = LocalWorkspaceInspector(allowed_root)

    assert inspector.is_directory(escaping_link) is False
