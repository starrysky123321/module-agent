from collections.abc import Sequence
from pathlib import Path

from module_agent.validation.adapters.files import (
    LocalRepositoryFileInspector,
)
from module_agent.validation.domain.ports import RepositoryFileInspector


def test_local_repository_file_inspector_satisfies_port(
    tmp_path: Path,
) -> None:
    inspector: RepositoryFileInspector = LocalRepositoryFileInspector(
        tmp_path
    )

    assert isinstance(inspector, LocalRepositoryFileInspector)


def test_list_root_files_returns_only_sorted_regular_files(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    repository = allowed_root / "repository"
    source_directory = repository / "src"
    source_directory.mkdir(parents=True)
    (repository / "README.md").write_text("readme", encoding="utf-8")
    (repository / "LICENSE").write_text("license", encoding="utf-8")
    (repository / "pyproject.toml").write_text("project", encoding="utf-8")
    (source_directory / "main.py").write_text("pass", encoding="utf-8")
    inspector = LocalRepositoryFileInspector(allowed_root)

    files: Sequence[str] = inspector.list_root_files(repository)

    assert files == ("LICENSE", "pyproject.toml", "README.md")
    assert "src" not in files
    assert "main.py" not in files


def test_list_root_files_returns_empty_tuple_for_missing_path(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    inspector = LocalRepositoryFileInspector(allowed_root)

    assert inspector.list_root_files(allowed_root / "missing") == ()


def test_list_root_files_returns_empty_tuple_for_regular_file(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    allowed_root.mkdir()
    regular_file = allowed_root / "not-a-repository"
    regular_file.write_text("example", encoding="utf-8")
    inspector = LocalRepositoryFileInspector(allowed_root)

    assert inspector.list_root_files(regular_file) == ()


def test_list_root_files_rejects_path_outside_allowed_root(
    tmp_path: Path,
) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    (outside_directory / "README.md").write_text("readme", encoding="utf-8")
    inspector = LocalRepositoryFileInspector(allowed_root)

    assert inspector.list_root_files(outside_directory) == ()


def test_list_root_files_rejects_symlink_escape(tmp_path: Path) -> None:
    allowed_root = tmp_path / "workspaces"
    outside_directory = tmp_path / "outside"
    allowed_root.mkdir()
    outside_directory.mkdir()
    (outside_directory / "README.md").write_text("readme", encoding="utf-8")
    escaping_link = allowed_root / "repository-link"
    escaping_link.symlink_to(outside_directory, target_is_directory=True)
    inspector = LocalRepositoryFileInspector(allowed_root)

    assert inspector.list_root_files(escaping_link) == ()
