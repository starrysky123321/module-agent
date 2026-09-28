import asyncio
from pathlib import Path

from module_agent.code.adapters.repository_analysis import (
    LocalRepositoryAnalyzer,
)
from module_agent.code.domain.request import CodePaperInput


def test_repository_analyzer_finds_dependencies_entrypoints_and_resources(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    (repository / "src").mkdir(parents=True)
    (repository / "pyproject.toml").write_text(
        "[project]\n"
        "dependencies = [\"torch>=2\", \"numpy>=1.26\"]\n",
        encoding="utf-8",
    )
    (repository / "train.py").write_text(
        "if __name__ == '__main__':\n    print('train')\n",
        encoding="utf-8",
    )
    (repository / "src" / "attention.py").write_text(
        "class AttentionModule:\n    pass\n",
        encoding="utf-8",
    )
    (repository / "README.md").write_text(
        "Download the ImageNet dataset before training.\n"
        "Pretrained checkpoint: model.pth\n",
        encoding="utf-8",
    )
    paper = CodePaperInput(
        paper_id=1,
        source="openalex",
        source_id="W1",
        title="Efficient Attention",
    )

    result = asyncio.run(
        LocalRepositoryAnalyzer().analyze(
            repository,
            paper,
            code_requirements="Reuse the attention module",
        )
    )

    assert result.dependency_files == ["pyproject.toml"]
    assert result.dependencies == ["numpy", "torch"]
    assert "train.py" in result.entrypoints
    assert "src/attention.py" in result.module_candidates
    assert "src/attention.py" in result.requirement_matches
    assert any("ImageNet dataset" in item for item in result.dataset_references)
    assert any("model.pth" in item for item in result.weight_references)


def test_repository_analyzer_does_not_follow_symlinks(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret dataset", encoding="utf-8")
    (repository / "linked.txt").symlink_to(outside)

    result = asyncio.run(
        LocalRepositoryAnalyzer().analyze(
            repository,
            CodePaperInput(
                paper_id=1,
                source="openalex",
                source_id="W1",
                title="Example",
            ),
        )
    )

    assert result.dataset_references == []
