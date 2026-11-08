import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from module_agent.code.adapters.qwen_reproduction import QwenReproductionPlanner
from module_agent.code.adapters.qwen_implementation import QwenReproductionCodeGenerator
from module_agent.code.domain.request import CodePaperInput
from module_agent.code.domain.artifact import ReproductionPlan
from module_agent.shared.llm.call import capture_model_calls


def paper():
    return CodePaperInput(
        paper_id=1, source="fixture", source_id="1", title="Fixture method"
    )


def client(parse):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(parse=parse))
    )


def test_planner_deadline_stops_waiting_and_records_timeout():
    stopped = []

    async def slow(**kwargs):
        try:
            await asyncio.sleep(10)
        finally:
            stopped.append(True)

    async def run():
        planner = QwenReproductionPlanner(
            client(slow), "fixture-model", timeout_seconds=0.02
        )
        with capture_model_calls() as calls:
            with pytest.raises(TimeoutError, match="已停止等待"):
                await planner.plan(paper())
            return calls

    calls = asyncio.run(run())
    assert stopped and len(calls) == 1 and calls[0].outcome == "timeout"
    assert calls[0].total_tokens is None


def test_missing_parsed_plan_is_failed_not_successful():
    parse = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=None))]
        )
    )

    async def run():
        with capture_model_calls() as calls:
            with pytest.raises(ValueError, match="no parsed"):
                await QwenReproductionPlanner(client(parse), "fixture").plan(paper())
            return calls

    assert asyncio.run(run())[0].outcome == "failed"


def test_provider_usage_is_preserved_not_estimated():
    plan = ReproductionPlan(
        research_problem="Fixture", implementation_steps=["Do not execute anything"]
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(parsed=plan))],
            usage=SimpleNamespace(
                prompt_tokens=100, completion_tokens=25, total_tokens=125
            ),
        )
    )

    async def run():
        with capture_model_calls() as calls:
            await QwenReproductionPlanner(client(parse), "fixture").plan(paper())
            return calls

    metric = asyncio.run(run())[0]
    assert metric.total_tokens == 125 and metric.outcome == "success"


@pytest.mark.parametrize(
    "adapter", [QwenReproductionPlanner, QwenReproductionCodeGenerator]
)
@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts_are_rejected(adapter, timeout):
    with pytest.raises(ValueError):
        adapter(client(AsyncMock()), "fixture", timeout_seconds=timeout)
