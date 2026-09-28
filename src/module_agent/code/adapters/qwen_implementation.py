"""Qwen adapter for bounded, unverified paper implementation generation."""

import json
import re
import time
import ast

from openai import AsyncOpenAI

from module_agent.code.domain.artifact import (
    GeneratedImplementation,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput
from module_agent.shared.llm.usage import (
    capture_completion_usage,
    clear_llm_token_usage,
)
from module_agent.shared.metrics import observe_llm_call


SYSTEM_PROMPT = """
You produce a small, reviewable Python candidate implementation of a computer
science paper method. Use only the supplied paper metadata, method profile, and
reproduction plan. Do not claim scientific equivalence or successful execution.

Return:
- algorithm_py: one self-contained Python module exposing run(inputs: dict) -> dict
- test_algorithm_py: deterministic pytest tests for the public behavior
- dependencies: only required PyPI package specifiers
- warnings: every assumption or missing paper detail that affects fidelity

Constraints:
- no network, subprocess, shell, dynamic eval/exec, filesystem deletion, or secrets
- no downloading datasets or weights
- keep the implementation deterministic and CPU-compatible by default
- represent underspecified paper operations with explicit, documented assumptions
""".strip()

_DEPENDENCY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:[<>=!~]=?[^\s]+)?$")


class QwenReproductionCodeGenerator:
    """Generate source as data; execution happens only in Validation sandbox."""

    def __init__(self, client: AsyncOpenAI, model: str) -> None:
        self.client = client
        self.model = model.strip()
        if not self.model:
            raise ValueError("model 不能为空")

    async def generate(
        self,
        paper: CodePaperInput,
        plan: ReproductionPlan,
        *,
        code_requirements: str | None = None,
    ) -> GeneratedImplementation:
        payload = {
            "paper": paper.model_dump(mode="json"),
            "plan": plan.model_dump(mode="json"),
            "code_requirements": code_requirements,
        }
        started_at = time.perf_counter()
        clear_llm_token_usage()
        try:
            completion = await self.client.chat.completions.parse(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    },
                ],
                response_format=GeneratedImplementation,
            )
            usage = capture_completion_usage(completion)
            result = completion.choices[0].message.parsed
            if result is None:
                raise ValueError("Qwen returned no parsed implementation")
            invalid = [
                dependency
                for dependency in result.dependencies
                if not _DEPENDENCY.fullmatch(dependency)
            ]
            if invalid:
                raise ValueError("Generated dependencies contain invalid specs")
            self._validate_source(result.algorithm_py, "algorithm_py")
            self._validate_source(result.test_algorithm_py, "test_algorithm_py")
        except Exception:
            observe_llm_call(
                stage="reproduction_implementation",
                model=self.model,
                outcome="failed",
                duration_seconds=time.perf_counter() - started_at,
            )
            raise
        observe_llm_call(
            stage="reproduction_implementation",
            model=self.model,
            outcome="success",
            duration_seconds=time.perf_counter() - started_at,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )
        return result

    @staticmethod
    def _validate_source(source: str, field: str) -> None:
        """Reject syntax errors and obvious host/network execution primitives."""
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            raise ValueError(f"Generated {field} is not valid Python") from exc
        forbidden_modules = {
            "httpx", "requests", "socket", "subprocess", "urllib"
        }
        forbidden_calls = {"eval", "exec", "compile", "__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(
                    alias.name.split(".", 1)[0] in forbidden_modules
                    for alias in node.names
                ):
                    raise ValueError(f"Generated {field} imports unsafe modules")
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".", 1)[0] in forbidden_modules:
                    raise ValueError(f"Generated {field} imports unsafe modules")
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in forbidden_calls
            ):
                raise ValueError(f"Generated {field} uses unsafe builtins")
