import asyncio
from collections.abc import Sequence

import pytest
from pydantic import ValidationError

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
    PaperRelevanceScorer,
)


@pytest.mark.parametrize("field", ["source", "source_id"])
def test_relevance_assessment_requires_non_empty_identity(field: str) -> None:
    values = {
        "source": "openalex",
        "source_id": "W123",
        "score": 0.5,
    }
    values[field] = ""

    with pytest.raises(ValidationError):
        PaperRelevanceAssessment.model_validate(values)


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_relevance_assessment_rejects_score_outside_unit_interval(
    score: float,
) -> None:
    with pytest.raises(ValidationError):
        PaperRelevanceAssessment(
            source="openalex",
            source_id="W123",
            score=score,
        )


def test_relevance_assessment_has_safe_defaults() -> None:
    assessment = PaperRelevanceAssessment(
        source="openalex",
        source_id="W123",
        score=0.75,
    )

    assert assessment.matched_terms == []
    assert assessment.reason == ""


def test_relevance_scorer_protocol_contract() -> None:
    class ExampleScorer:
        async def score_many(
            self,
            request: SearchRequest,
            search_queries: Sequence[str],
            papers: Sequence[PaperSearchResult],
        ) -> PaperRelevanceResult:
            return PaperRelevanceResult(
                assessments=[
                    PaperRelevanceAssessment(
                        source=paper.source,
                        source_id=paper.source_id,
                        score=1.0,
                    )
                    for paper in papers
                ]
            )

    scorer: PaperRelevanceScorer = ExampleScorer()
    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Example paper",
    )
    request = SearchRequest(
        topic="example",
        description="Example literature request",
        start_date="2025-01-01",
        end_date="2025-12-31",
        keywords=[],
        max_results=10,
    )

    result = asyncio.run(
        scorer.score_many(request, ["example"], [paper])
    )

    assert result.assessments == [
        PaperRelevanceAssessment(
            source="openalex",
            source_id="W123",
            score=1.0,
        )
    ]
    assert result.warnings == []


def test_paper_relevance_result_defaults_to_empty_lists() -> None:
    result = PaperRelevanceResult()

    assert result.assessments == []
    assert result.warnings == []
