import asyncio
from pathlib import Path

import pytest

from module_agent.code.adapters.reproduction import LocalReproductionBuilder
from module_agent.code.domain.artifact import (
    GeneratedImplementation,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput


def test_reproduction_builder_creates_traceable_scaffold(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "reproduction"
    plan = ReproductionPlan(
        research_problem="Classify graph nodes",
        implementation_steps=["Load graph", "Apply message passing"],
        inputs=["graph"],
        outputs=["labels"],
        suggested_dependencies=["torch"],
    )

    scaffold = asyncio.run(
        LocalReproductionBuilder().build(
            destination,
            CodePaperInput(
                paper_id=1,
                source="openalex",
                source_id="W1",
                title="Graph Method",
            ),
            plan,
        )
    )

    assert scaffold.local_path == str(destination.resolve())
    assert "README.md" in scaffold.files
    assert "reproduction_plan.json" in scaffold.files
    assert "src/paper_reproduction/core.py" in scaffold.files
    assert "not a verified implementation" in (
        destination / "README.md"
    ).read_text(encoding="utf-8")
    compile(
        (destination / "src/paper_reproduction/core.py").read_text(
            encoding="utf-8"
        ),
        "core.py",
        "exec",
    )


def test_reproduction_builder_never_overwrites_existing_directory(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "reproduction"
    destination.mkdir()
    marker = destination / "user-file.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        asyncio.run(
            LocalReproductionBuilder().build(
                destination,
                CodePaperInput(
                    paper_id=1,
                    source="openalex",
                    source_id="W1",
                    title="Graph Method",
                ),
                ReproductionPlan(
                    research_problem="Graph learning",
                    implementation_steps=["Implement"],
                ),
            )
        )

    assert marker.read_text(encoding="utf-8") == "keep"


def test_reproduction_builder_writes_unverified_candidate_code(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "candidate"
    scaffold = asyncio.run(
        LocalReproductionBuilder().build(
            destination,
            CodePaperInput(
                paper_id=1,
                source="openalex",
                source_id="W1",
                title="Graph Method",
            ),
            ReproductionPlan(
                research_problem="Graph learning",
                implementation_steps=["Aggregate neighbors"],
            ),
            implementation=GeneratedImplementation(
                algorithm_py="def run(inputs: dict) -> dict:\n    return inputs",
                test_algorithm_py=(
                    "from paper_reproduction import run\n\n"
                    "def test_run():\n    assert run({'x': 1}) == {'x': 1}"
                ),
                dependencies=["numpy>=2"],
            ),
        )
    )

    assert "src/paper_reproduction/algorithm.py" in scaffold.files
    assert "tests/test_algorithm.py" in scaffold.files
    assert "numpy>=2" in (destination / "pyproject.toml").read_text()
    assert "must pass sandbox validation" in (
        destination / "README.md"
    ).read_text()
