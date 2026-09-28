import asyncio
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.query import LiteratureQueryPlan
from module_agent.literature.domain.query import MAX_SEARCH_QUERIES
from module_agent.literature.adapters.llm.qwen_query_planner import (
    SYSTEM_PROMPT,
    QwenLiteratureQueryPlanner,
    QwenQueryPlanResponse,
)


def search_request() -> SearchRequest:
    return SearchRequest(
        topic="小目标检测",
        description="寻找遥感图像中的小目标检测算法",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        venues=["CVPR"],
        keywords=["遥感"],
        max_results=10,
    )


def qwen_client_with_parsed_result(
    parsed: LiteratureQueryPlan | None,
) -> tuple[MagicMock, AsyncMock]:
    parse = AsyncMock()
    parse.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(parsed=parsed))]
    )
    client = MagicMock(spec=AsyncOpenAI)
    client.chat.completions.parse = parse
    return client, parse


def test_qwen_planner_validates_and_normalizes_model_name() -> None:
    client, _ = qwen_client_with_parsed_result(None)

    planner = QwenLiteratureQueryPlanner(client, "  qwen3.7-plus  ")

    assert planner.model == "qwen3.7-plus"
    with pytest.raises(ValueError, match="model"):
        QwenLiteratureQueryPlanner(client, "   ")


def test_qwen_prompt_uses_structured_query_limit() -> None:
    assert f"Generate 3 to {MAX_SEARCH_QUERIES}" in SYSTEM_PROMPT


def test_qwen_planner_returns_structured_query_plan() -> None:
    expected = LiteratureQueryPlan(
        search_queries=[
            "small object detection",
            "remote sensing tiny object detection",
        ]
    )
    client, parse = qwen_client_with_parsed_result(expected)
    planner = QwenLiteratureQueryPlanner(client, "qwen3.7-plus")
    request = search_request()

    result = asyncio.run(planner.plan(request))

    assert result == expected
    parse.assert_awaited_once_with(
        model="qwen3.7-plus",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": request.model_dump_json()},
        ],
        response_format=QwenQueryPlanResponse,
    )


def test_qwen_planner_rejects_missing_parsed_result() -> None:
    client, _ = qwen_client_with_parsed_result(None)
    planner = QwenLiteratureQueryPlanner(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="no parsed query plan"):
        asyncio.run(planner.plan(search_request()))
