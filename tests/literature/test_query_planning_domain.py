import pytest
from pydantic import ValidationError

from module_agent.literature.domain.query import (
    LiteratureQueryPlan,
    MAX_SEARCH_QUERIES,
)


def test_query_plan_normalizes_valid_queries() -> None:
    plan = LiteratureQueryPlan(
        search_queries=[
            "  small object detection  ",
            "tiny object detection",
        ]
    )

    assert plan.search_queries == [
        "small object detection",
        "tiny object detection",
    ]
    assert plan.warnings == []


@pytest.mark.parametrize(
    "queries",
    [
        [],
        ["   "],
        [f"query-{index}" for index in range(MAX_SEARCH_QUERIES + 1)],
    ],
)
def test_query_plan_rejects_invalid_queries(queries: list[str]) -> None:
    with pytest.raises(ValidationError):
        LiteratureQueryPlan(search_queries=queries)
