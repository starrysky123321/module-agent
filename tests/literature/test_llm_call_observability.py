import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.llm_metric import LlmCallOutcome
from module_agent.literature.domain.method import (
    PaperMethodExtractionResult,
    PaperMethodExtractor,
    PaperMethodProfile,
)
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
    PaperRelevanceScorer,
)
from module_agent.literature.domain.query import (
    LiteratureQueryPlan,
    LiteratureQueryPlanner,
)
from module_agent.literature.application.query_planning import (
    FallbackLiteratureQueryPlanner,
)
from module_agent.literature.application.method_extraction import (
    BatchedPaperMethodExtractor,
    FallbackPaperMethodExtractor,
)
from module_agent.literature.application.relevance import FallbackPaperRelevanceScorer


def request() -> SearchRequest:
    return SearchRequest(
        topic="graph learning",
        description="Find graph learning methods",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["GNN"],
        max_results=11,
    )


def paper(source_id: str = "W1") -> PaperSearchResult:
    return PaperSearchResult(
        source="openalex", source_id=source_id, title="Graph Learning Paper"
    )


def test_query_planner_records_successful_model_call() -> None:
    primary = AsyncMock(spec=LiteratureQueryPlanner)
    primary.plan.return_value = LiteratureQueryPlan(search_queries=["GNN method"])
    fallback = AsyncMock(spec=LiteratureQueryPlanner)
    planner = FallbackLiteratureQueryPlanner(
        primary, fallback, timeout_seconds=1, model="test-qwen"
    )

    result = asyncio.run(planner.plan(request()))

    assert result.search_queries == ["GNN method"]
    assert len(result.llm_metrics) == 1
    metric = result.llm_metrics[0]
    assert metric.stage == "query_planning"
    assert metric.model == "test-qwen"
    assert metric.item_count == 1
    assert metric.outcome is LlmCallOutcome.SUCCESS
    assert metric.duration_ms >= 0
    fallback.plan.assert_not_awaited()


def test_query_planner_timeout_uses_rule_fallback_and_records_error() -> None:
    primary = AsyncMock(spec=LiteratureQueryPlanner)

    async def slow_plan(_: SearchRequest) -> LiteratureQueryPlan:
        await asyncio.sleep(1)
        return LiteratureQueryPlan(search_queries=["late"])

    primary.plan.side_effect = slow_plan
    fallback = AsyncMock(spec=LiteratureQueryPlanner)
    fallback.plan.return_value = LiteratureQueryPlan(search_queries=["rule query"])
    planner = FallbackLiteratureQueryPlanner(
        primary, fallback, timeout_seconds=0.01, model="test-qwen"
    )

    result = asyncio.run(planner.plan(request()))

    assert result.search_queries == ["rule query"]
    assert result.llm_metrics[0].outcome is LlmCallOutcome.FALLBACK
    assert result.llm_metrics[0].error_type == "TimeoutError"
    assert result.llm_metrics[0].duration_ms >= 5
    fallback.plan.assert_awaited_once()


def test_relevance_timeout_records_paper_count_and_fallback() -> None:
    candidate = paper()
    primary = AsyncMock(spec=PaperRelevanceScorer)

    async def slow_score(*_: object) -> PaperRelevanceResult:
        await asyncio.sleep(1)
        return PaperRelevanceResult()

    primary.score_many.side_effect = slow_score
    fallback = AsyncMock(spec=PaperRelevanceScorer)
    fallback.score_many.return_value = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source=candidate.source, source_id=candidate.source_id, score=0.5
            )
        ]
    )
    scorer = FallbackPaperRelevanceScorer(
        primary, fallback, timeout_seconds=0.01, model="test-qwen"
    )

    result = asyncio.run(scorer.score_many(request(), ["GNN"], [candidate]))

    assert result.assessments[0].score == 0.5
    assert len(result.llm_metrics) == 1
    metric = result.llm_metrics[0]
    assert metric.stage == "relevance_scoring"
    assert metric.item_count == 1
    assert metric.outcome is LlmCallOutcome.FALLBACK
    assert metric.error_type == "TimeoutError"


def test_method_extraction_timeout_returns_unknown_profile_and_metric() -> None:
    candidate = paper()
    primary = AsyncMock(spec=PaperMethodExtractor)

    async def slow_extract(*_: object) -> PaperMethodExtractionResult:
        await asyncio.sleep(1)
        return PaperMethodExtractionResult()

    primary.extract_many.side_effect = slow_extract
    extractor = FallbackPaperMethodExtractor(
        primary, timeout_seconds=0.01, model="test-qwen"
    )

    result = asyncio.run(extractor.extract_many(request(), [candidate]))

    assert result.profiles[0].confidence == 0
    assert len(result.llm_metrics) == 1
    metric = result.llm_metrics[0]
    assert metric.stage == "method_extraction"
    assert metric.outcome is LlmCallOutcome.FALLBACK
    assert metric.error_type == "TimeoutError"


def test_batched_method_extraction_records_one_metric_per_model_call() -> None:
    papers = [paper(f"W{index}") for index in range(11)]
    primary = AsyncMock(spec=PaperMethodExtractor)

    async def extract_batch(
        _: SearchRequest, batch: list[PaperSearchResult]
    ) -> PaperMethodExtractionResult:
        return PaperMethodExtractionResult(
            profiles=[
                PaperMethodProfile(
                    source=item.source, source_id=item.source_id, confidence=0.5
                )
                for item in batch
            ]
        )

    primary.extract_many.side_effect = extract_batch
    extractor = BatchedPaperMethodExtractor(
        FallbackPaperMethodExtractor(
            primary, timeout_seconds=1, model="test-qwen"
        ),
        batch_size=10,
    )

    result = asyncio.run(extractor.extract_many(request(), papers))

    assert len(result.profiles) == 11
    assert [metric.item_count for metric in result.llm_metrics] == [10, 1]
    assert all(metric.outcome is LlmCallOutcome.SUCCESS for metric in result.llm_metrics)


def test_configured_model_cancellation_is_not_recorded_as_fallback() -> None:
    primary = AsyncMock(spec=PaperMethodExtractor)
    primary.extract_many.side_effect = asyncio.CancelledError()
    extractor = FallbackPaperMethodExtractor(
        primary, timeout_seconds=1, model="test-qwen"
    )

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extractor.extract_many(request(), [paper()]))


@pytest.mark.parametrize("timeout", [0, -1])
def test_observed_fallbacks_reject_invalid_timeout(timeout: float) -> None:
    with pytest.raises(ValueError, match="greater than zero"):
        FallbackPaperMethodExtractor(
            AsyncMock(spec=PaperMethodExtractor), timeout_seconds=timeout
        )
