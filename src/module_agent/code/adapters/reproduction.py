import asyncio
import json
from pathlib import Path

from module_agent.code.domain.artifact import (
    ReproductionPlan,
    ReproductionScaffold,
    GeneratedImplementation,
)
from module_agent.code.domain.request import CodePaperInput


class LocalReproductionBuilder:
    """把计划写成可导入、可运行但明确未完成算法逻辑的工程骨架。"""

    async def build(
        self,
        destination: Path,
        paper: CodePaperInput,
        plan: ReproductionPlan,
        *,
        implementation: GeneratedImplementation | None = None,
    ) -> ReproductionScaffold:
        """在线程中创建复现目录及基础文件。"""
        return await asyncio.to_thread(
            self._build,
            destination,
            paper,
            plan,
            implementation,
        )

    @staticmethod
    def _build(
        destination: Path,
        paper: CodePaperInput,
        plan: ReproductionPlan,
        implementation: GeneratedImplementation | None = None,
    ) -> ReproductionScaffold:
        destination = destination.resolve()
        if destination.exists():
            raise FileExistsError(
                f"Reproduction destination already exists: {destination}"
            )

        package = destination / "src" / "paper_reproduction"
        package.mkdir(parents=True)
        (destination / "examples").mkdir()

        payload = {
            "paper_title": paper.title,
            "research_problem": plan.research_problem,
            "implementation_steps": plan.implementation_steps,
            "inputs": plan.inputs,
            "outputs": plan.outputs,
            "suggested_dependencies": plan.suggested_dependencies,
            "open_questions": plan.open_questions,
            "warnings": plan.warnings,
        }
        (destination / "reproduction_plan.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (destination / "examples" / "input.json").write_text(
            json.dumps(
                {name: None for name in plan.inputs} or {"input": None},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        dependencies = (
            implementation.dependencies
            if implementation is not None
            else []
        )
        dependencies_toml = json.dumps(dependencies, ensure_ascii=False)
        (destination / "pyproject.toml").write_text(
            "[build-system]\n"
            'requires = ["hatchling"]\n'
            'build-backend = "hatchling.build"\n\n'
            "[project]\n"
            'name = "paper-reproduction-scaffold"\n'
            'version = "0.1.0"\n'
            'description = "Generated research reproduction scaffold"\n'
            'requires-python = ">=3.12"\n'
            f"dependencies = {dependencies_toml}\n",
            encoding="utf-8",
        )
        (package / "__init__.py").write_text(
            (
                'from .algorithm import run\n\n__all__ = ["run"]\n'
                if implementation is not None
                else 'from .core import run\n\n__all__ = ["run"]\n'
            ),
            encoding="utf-8",
        )
        steps_literal = repr(list(plan.implementation_steps))
        (package / "core.py").write_text(
            '"""Generated scaffold; paper-specific algorithm logic is pending."""\n\n'
            "from typing import Any\n\n"
            f"IMPLEMENTATION_STEPS = {steps_literal}\n\n"
            "def run(inputs: dict[str, Any]) -> dict[str, Any]:\n"
            '    """Return a traceable placeholder result for integration work."""\n'
            "    return {\n"
            '        "status": "scaffold",\n'
            '        "inputs": inputs,\n'
            '        "implementation_steps": IMPLEMENTATION_STEPS,\n'
            "    }\n",
            encoding="utf-8",
        )
        if implementation is not None:
            (package / "algorithm.py").write_text(
                implementation.algorithm_py.rstrip() + "\n",
                encoding="utf-8",
            )
            tests = destination / "tests"
            tests.mkdir()
            (tests / "test_algorithm.py").write_text(
                implementation.test_algorithm_py.rstrip() + "\n",
                encoding="utf-8",
            )
        (package / "__main__.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            "from . import run\n\n"
            "example = Path(__file__).parents[2] / 'examples' / 'input.json'\n"
            "print(json.dumps(run(json.loads(example.read_text())), indent=2))\n",
            encoding="utf-8",
        )
        (destination / "README.md").write_text(
            f"# Reproduction scaffold: {paper.title}\n\n"
            "> This is a generated engineering scaffold, not a verified "
            "implementation of the paper.\n\n"
            "## Research problem\n\n"
            f"{plan.research_problem}\n\n"
            "## Run the scaffold\n\n"
            "```bash\nPYTHONPATH=src python -m paper_reproduction\n```\n\n"
            "Review `reproduction_plan.json` before implementing the method.\n"
            + (
                "\n`algorithm.py` is an AI-generated candidate and must pass "
                "sandbox validation before use.\n"
                if implementation is not None
                else ""
            ),
            encoding="utf-8",
        )

        files = sorted(
            path.relative_to(destination).as_posix()
            for path in destination.rglob("*")
            if path.is_file()
        )
        return ReproductionScaffold(
            local_path=str(destination),
            files=files,
        )
