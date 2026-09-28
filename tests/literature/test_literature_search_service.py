import asyncio
from datetime import date

import pytest

from module_agent.shared.exceptions import LiteratureSourceSkippedError
from module_agent.literature.domain.search import (
    PaperSearchResult,
    SearchRequest,
    SourceSearchOutcome,
)
from module_agent.literature.application.search import LiteratureSearchService


def search_request() -> SearchRequest:
    return SearchRequest(
        topic="graph neural networks",
        description="Find representative papers",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )


def paper(source: str, source_id: str) -> PaperSearchResult:
    return PaperSearchResult(
        source=source,
        source_id=source_id,
        title=f"Paper {source_id}",
    )


def test_search_service_combines_successful_sources() -> None:
    async def search_first(_: SearchRequest) -> list[PaperSearchResult]:
        return [paper("first", "1")]

    async def search_second(_: SearchRequest) -> list[PaperSearchResult]:
        return [paper("second", "2")]

    service = LiteratureSearchService([search_first, search_second])

    response = asyncio.run(service.search(search_request()))

    assert [result.source_id for result in response.results] == ["1", "2"]
    assert response.warnings == []
    assert [metric.source for metric in response.source_metrics] == [
        "search_first",
        "search_second",
    ]
    assert [metric.result_count for metric in response.source_metrics] == [1, 1]
    assert all(
        metric.outcome is SourceSearchOutcome.SUCCESS
        for metric in response.source_metrics
    )
    assert all(metric.error_type is None for metric in response.source_metrics)
    assert all(metric.duration_ms >= 0 for metric in response.source_metrics)


def test_search_service_keeps_results_when_one_source_fails() -> None:
    async def search_failed(_: SearchRequest) -> list[PaperSearchResult]:
        raise TimeoutError("request timed out")

    async def search_successful(_: SearchRequest) -> list[PaperSearchResult]:
        return [paper("successful", "2")]

    service = LiteratureSearchService([search_failed, search_successful])

    response = asyncio.run(service.search(search_request()))

    assert [result.source_id for result in response.results] == ["2"]
    assert response.warnings == [
        "search_failed failed: TimeoutError: request timed out"
    ]
    failed_metric, successful_metric = response.source_metrics
    assert failed_metric.source == "search_failed"
    assert failed_metric.query == "graph neural networks"
    assert failed_metric.result_count == 0
    assert failed_metric.outcome is SourceSearchOutcome.FAILED
    assert failed_metric.error_type == "TimeoutError"
    assert successful_metric.source == "search_successful"
    assert successful_metric.result_count == 1
    assert successful_metric.outcome is SourceSearchOutcome.SUCCESS


def test_search_service_marks_intentionally_skipped_source() -> None:
    async def search_skipped(_: SearchRequest) -> list[PaperSearchResult]:
        raise LiteratureSourceSkippedError("circuit breaker is open")

    async def search_successful(_: SearchRequest) -> list[PaperSearchResult]:
        return [paper("successful", "2")]

    service = LiteratureSearchService([search_skipped, search_successful])

    response = asyncio.run(service.search(search_request()))

    skipped_metric, successful_metric = response.source_metrics
    assert skipped_metric.outcome is SourceSearchOutcome.SKIPPED
    assert skipped_metric.error_type == "LiteratureSourceSkippedError"
    assert successful_metric.outcome is SourceSearchOutcome.SUCCESS
    assert response.warnings == [
        "search_skipped skipped: LiteratureSourceSkippedError: "
        "circuit breaker is open"
    ]


def test_search_service_raises_first_error_when_all_sources_fail() -> None:
    first_error = TimeoutError("first source timed out")

    async def search_first(_: SearchRequest) -> list[PaperSearchResult]:
        raise first_error

    async def search_second(_: SearchRequest) -> list[PaperSearchResult]:
        raise RuntimeError("second source failed")

    service = LiteratureSearchService([search_first, search_second])

    with pytest.raises(TimeoutError) as captured:
        asyncio.run(service.search(search_request()))

    assert captured.value is first_error
