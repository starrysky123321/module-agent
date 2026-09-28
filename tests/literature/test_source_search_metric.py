import pytest
from pydantic import ValidationError

from module_agent.literature.domain.search import (
    SourceSearchMetric,
    SourceSearchOutcome,
)


def test_source_search_metric_accepts_outcomes() -> None:
    success = SourceSearchMetric(
        source="search_openalex",
        query="graph neural networks",
        duration_ms=10.5,
        result_count=3,
        outcome=SourceSearchOutcome.SUCCESS,
    )
    failure = SourceSearchMetric(
        source="search_semantic_scholar",
        query="graph neural networks",
        duration_ms=20.0,
        result_count=0,
        outcome=SourceSearchOutcome.FAILED,
        error_type="HTTPStatusError",
    )

    assert success.error_type is None
    assert success.outcome is SourceSearchOutcome.SUCCESS
    assert failure.error_type == "HTTPStatusError"
    assert failure.outcome is SourceSearchOutcome.FAILED


@pytest.mark.parametrize(
    ("legacy_success", "expected"),
    [
        (True, SourceSearchOutcome.SUCCESS),
        (False, SourceSearchOutcome.FAILED),
    ],
)
def test_source_search_metric_migrates_legacy_success(
    legacy_success: bool,
    expected: SourceSearchOutcome,
) -> None:
    metric = SourceSearchMetric.model_validate(
        {
            "source": "search_openalex",
            "query": "graph neural networks",
            "duration_ms": 10.5,
            "result_count": 3,
            "success": legacy_success,
        }
    )

    assert metric.outcome is expected
    assert "success" not in metric.model_dump()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source", ""),
        ("query", ""),
        ("duration_ms", -0.1),
        ("result_count", -1),
    ],
)
def test_source_search_metric_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    values: dict[str, object] = {
        "source": "search_openalex",
        "query": "graph neural networks",
        "duration_ms": 10.0,
        "result_count": 1,
        "outcome": SourceSearchOutcome.SUCCESS,
    }
    values[field] = value

    with pytest.raises(ValidationError):
        SourceSearchMetric.model_validate(values)
