import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.code.adapters.qwen_reproduction import (
    SYSTEM_PROMPT,
    QwenReproductionPlanner,
)
from module_agent.code.domain.artifact import ReproductionPlan
from module_agent.code.domain.request import CodePaperInput
from module_agent.literature.domain.method import PaperMethodProfile


def make_paper() -> CodePaperInput:
    return CodePaperInput(
        paper_id=9,
        source="openalex",
        source_id="W123",
        title="Mitigating Oversmoothing in Graph Neural Networks",
        authors=["Alice Example"],
        doi="10.1000/example",
        abstract="We propose an adaptive propagation module.",
        method_profile=PaperMethodProfile(
            source="openalex",
            source_id="W123",
            research_problem="Graph neural network oversmoothing",
            module_type="adaptive propagation",
            core_method="Preserve node feature diversity",
            inputs=["node features"],
            outputs=["updated node features"],
            confidence=0.9,
        ),
    )


def client_with_result(
    parsed: ReproductionPlan | None,
) -> tuple[MagicMock, AsyncMock]:
    parse = AsyncMock(
        return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(parsed=parsed))]
        )
    )
    client = MagicMock(spec=AsyncOpenAI)
    client.chat.completions.parse = parse
    return client, parse


def test_planner_normalizes_and_validates_model_name() -> None:
    client, _ = client_with_result(None)

    planner = QwenReproductionPlanner(client, "  qwen3.7-plus  ")

    assert planner.model == "qwen3.7-plus"
    with pytest.raises(ValueError, match="model"):
        QwenReproductionPlanner(client, "   ")


def test_planner_returns_structured_reproduction_plan() -> None:
    expected = ReproductionPlan(
        research_problem="Graph neural network oversmoothing",
        implementation_steps=[
            "Implement the adaptive propagation layer",
            "Add unit tests for tensor shapes",
        ],
        inputs=["node features"],
        outputs=["updated node features"],
        suggested_dependencies=["torch"],
        open_questions=["The propagation equation is not in the abstract"],
        warnings=["The plan has not been executed"],
    )
    client, parse = client_with_result(expected)
    planner = QwenReproductionPlanner(client, "qwen3.7-plus")

    result = asyncio.run(
        planner.plan(make_paper(), code_requirements="Use PyTorch")
    )

    assert result == expected
    call = parse.await_args.kwargs
    assert call["model"] == "qwen3.7-plus"
    assert call["response_format"] is ReproductionPlan
    assert call["messages"][0] == {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    payload = json.loads(call["messages"][1]["content"])
    assert payload["paper"]["paper_id"] == 9
    assert payload["paper"]["title"] == make_paper().title
    assert payload["paper"]["method_profile"]["core_method"] == (
        "Preserve node feature diversity"
    )
    assert payload["code_requirements"] == "Use PyTorch"


def test_planner_preserves_absent_requirements() -> None:
    expected = ReproductionPlan(
        research_problem="Graph neural network oversmoothing",
        implementation_steps=["Implement the method"],
    )
    client, parse = client_with_result(expected)
    planner = QwenReproductionPlanner(client, "qwen3.7-plus")

    asyncio.run(planner.plan(make_paper()))

    payload = json.loads(
        parse.await_args.kwargs["messages"][1]["content"]
    )
    assert payload["code_requirements"] is None


def test_planner_rejects_missing_parsed_result() -> None:
    client, _ = client_with_result(None)
    planner = QwenReproductionPlanner(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="no parsed reproduction plan"):
        asyncio.run(planner.plan(make_paper()))
