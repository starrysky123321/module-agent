import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.query import (
    LiteratureQueryPlan,
    LiteratureQueryPlanner,
    MAX_SEARCH_QUERIES,
)
from module_agent.literature.application.query_planning import (
    FallbackLiteratureQueryPlanner,
    RuleBasedLiteratureQueryPlanner,
)


def request_with_keywords(keywords: list[str]) -> SearchRequest:
    return SearchRequest(
        topic="  small   object detection  ",
        description="Plan literature queries",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=keywords,
        max_results=10,
    )


def test_rule_planner_normalizes_and_deduplicates_queries() -> None:
    planner = RuleBasedLiteratureQueryPlanner()

    plan = asyncio.run(
        planner.plan(
            request_with_keywords(
                [
                    "   ",
                    "SMALL OBJECT DETECTION",
                    " remote   sensing ",
                    "REMOTE SENSING",
                    "tiny objects",
                ]
            )
        )
    )

    assert plan.search_queries == [
        "small object detection",
        "small object detection remote sensing",
        "small object detection tiny objects",
    ]


def test_rule_planner_limits_plan_to_configured_maximum() -> None:
    planner = RuleBasedLiteratureQueryPlanner()
    request = request_with_keywords(
        [f"keyword {index}" for index in range(20)]
    )

    plan = asyncio.run(planner.plan(request))

    assert len(plan.search_queries) == MAX_SEARCH_QUERIES
    assert plan.search_queries[0] == "small object detection"
    assert plan.search_queries[-1] == "small object detection keyword 3"


def test_fallback_planner_returns_primary_plan_when_primary_succeeds() -> None:
    primary_plan = LiteratureQueryPlan(search_queries=["llm query"])
    primary = AsyncMock(spec=LiteratureQueryPlanner)
    primary.plan.return_value = primary_plan
    fallback = AsyncMock(spec=LiteratureQueryPlanner)
    planner = FallbackLiteratureQueryPlanner(primary, fallback)
    request = request_with_keywords([])

    result = asyncio.run(planner.plan(request))

    assert result is primary_plan
    primary.plan.assert_awaited_once_with(request)
    fallback.plan.assert_not_awaited()


def test_fallback_planner_uses_copy_of_fallback_plan_with_warning() -> None:
    primary = AsyncMock(spec=LiteratureQueryPlanner)
    primary.plan.side_effect = RuntimeError("model unavailable")
    fallback_plan = LiteratureQueryPlan(
        search_queries=["rule query"],
        warnings=[
            "Existing warning",
            "Existing warning",
        ],
    )
    fallback = AsyncMock(spec=LiteratureQueryPlanner)
    fallback.plan.return_value = fallback_plan
    planner = FallbackLiteratureQueryPlanner(primary, fallback)
    request = request_with_keywords([])

    result = asyncio.run(planner.plan(request))

    assert result is not fallback_plan
    assert result.search_queries == ["rule query"]
    assert result.warnings == [
        "Existing warning",
        "Primary query planner failed; fallback query planner was used",
    ]
    assert fallback_plan.warnings == [
        "Existing warning",
        "Existing warning",
    ]
    fallback.plan.assert_awaited_once_with(request)


def test_fallback_planner_propagates_fallback_failure() -> None:
    primary = AsyncMock(spec=LiteratureQueryPlanner)
    primary.plan.side_effect = RuntimeError("model unavailable")
    fallback_error = ValueError("fallback failed")
    fallback = AsyncMock(spec=LiteratureQueryPlanner)
    fallback.plan.side_effect = fallback_error
    planner = FallbackLiteratureQueryPlanner(primary, fallback)

    with pytest.raises(ValueError) as captured:
        asyncio.run(planner.plan(request_with_keywords([])))

    assert captured.value is fallback_error
