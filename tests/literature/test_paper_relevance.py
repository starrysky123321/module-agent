import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
    PaperRelevanceScorer,
)
from module_agent.literature.application.relevance import (
    FallbackPaperRelevanceScorer,
    RuleBasedPaperRelevanceScorer,
    ShortlistingPaperRelevanceScorer,
    _score_query,
    _tokenize,
)


def test_tokenize_normalizes_and_filters_stop_words() -> None:
    assert _tokenize(
        "Small Object Detection in Remote Sensing Images"
    ) == {
        "small",
        "object",
        "detection",
        "remote",
        "sensing",
        "images",
    }


def test_tokenize_removes_punctuation_and_duplicates() -> None:
    assert _tokenize("YOLO-based YOLO: Version 11!") == {
        "yolo",
        "version",
        "11",
    }


def test_tokenize_normalizes_oversmoothing_spelling() -> None:
    assert _tokenize(
        "over-smoothing over smoothing oversmoothing"
    ) == {"oversmoothing"}


@pytest.mark.parametrize("text", ["", "THE and Of"])
def test_tokenize_can_return_empty_set(text: str) -> None:
    assert _tokenize(text) == set()


def test_score_query_prefers_title_match_over_abstract_match() -> None:
    score, matched_terms = _score_query(
        query_terms={"small", "object", "detection", "remote"},
        title_terms={"small", "object"},
        abstract_terms={"small", "detection", "remote"},
    )

    assert score == pytest.approx(0.75)
    assert matched_terms == {"small", "object", "detection", "remote"}


def test_score_query_returns_full_score_for_title_matches() -> None:
    score, matched_terms = _score_query(
        query_terms={"small", "object"},
        title_terms={"small", "object"},
        abstract_terms=set(),
    )

    assert score == 1.0
    assert matched_terms == {"small", "object"}


@pytest.mark.parametrize("query_terms", [set(), {"unmatched"}])
def test_score_query_returns_zero_without_matches(
    query_terms: set[str],
) -> None:
    score, matched_terms = _score_query(
        query_terms=query_terms,
        title_terms={"small"},
        abstract_terms={"detection"},
    )

    assert score == 0.0
    assert matched_terms == set()


def test_rule_scorer_selects_best_query_and_preserves_paper_order() -> None:
    scorer: PaperRelevanceScorer = RuleBasedPaperRelevanceScorer()
    request = SearchRequest(
        topic="remote sensing object detection",
        description="Find lightweight detection methods",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=["lightweight detector"],
        max_results=10,
    )
    papers = (
        PaperSearchResult(
            source="openalex",
            source_id="relevant",
            title="Lightweight Detector for Aerial Images",
        ),
        PaperSearchResult(
            source="semantic_scholar",
            source_id="broad-review",
            title="A Review of Computer Vision",
            abstract="Small object detection in remote sensing.",
        ),
    )

    result = asyncio.run(
        scorer.score_many(
            request,
            (
                "small object detection remote sensing",
                "lightweight detector",
            ),
            papers,
        )
    )

    assessments = result.assessments
    assert [item.source_id for item in assessments] == [
        "relevant",
        "broad-review",
    ]
    assert assessments[0].score == 1.0
    assert assessments[0].matched_terms == ["detector", "lightweight"]
    assert assessments[0].reason == "Matched 2 search terms"
    assert assessments[1].score == pytest.approx(0.5)


def test_rule_scorer_falls_back_to_topic_and_keywords() -> None:
    scorer = RuleBasedPaperRelevanceScorer()
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["transformer"],
        max_results=10,
    )
    paper = PaperSearchResult(
        source="openalex",
        source_id="transformer-paper",
        title="Transformer Architecture",
    )

    result = asyncio.run(
        scorer.score_many(request, (), (paper,))
    )

    assert result.assessments[0].score == 1.0
    assert result.assessments[0].matched_terms == ["transformer"]


def test_rule_scorer_returns_empty_list_for_empty_papers() -> None:
    scorer = RuleBasedPaperRelevanceScorer()
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )

    result = asyncio.run(scorer.score_many(request, (), ()))

    assert result.assessments == []
    assert result.warnings == []


def test_rule_scorer_caps_review_for_method_focused_request() -> None:
    scorer = RuleBasedPaperRelevanceScorer()
    request = SearchRequest(
        topic="GNN oversmoothing",
        description="Find a reusable algorithm module",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    survey = PaperSearchResult(
        source="openalex",
        source_id="survey",
        title="A Survey of GNN Over-Smoothing",
        publication_type="review",
    )

    result = asyncio.run(
        scorer.score_many(request, ["GNN oversmoothing"], [survey])
    )

    assert result.assessments[0].score == 0.5
    assert "review capped" in result.assessments[0].reason


def test_rule_scorer_does_not_cap_explicit_review_request() -> None:
    scorer = RuleBasedPaperRelevanceScorer()
    request = SearchRequest(
        topic="GNN oversmoothing survey",
        description="Find a comprehensive review",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    survey = PaperSearchResult(
        source="openalex",
        source_id="survey",
        title="A Survey of GNN Oversmoothing",
        publication_type="review",
    )

    result = asyncio.run(
        scorer.score_many(
            request,
            ["GNN oversmoothing survey"],
            [survey],
        )
    )

    assert result.assessments[0].score == 1.0
    assert "review capped" not in result.assessments[0].reason


def test_fallback_scorer_returns_primary_result() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    primary_result = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source="openalex",
                source_id="W123",
                score=0.9,
            )
        ]
    )
    primary = AsyncMock(spec=PaperRelevanceScorer)
    primary.score_many.return_value = primary_result
    fallback = AsyncMock(spec=PaperRelevanceScorer)
    scorer = FallbackPaperRelevanceScorer(primary, fallback)

    result = asyncio.run(scorer.score_many(request, [], []))

    assert result is primary_result
    primary.score_many.assert_awaited_once_with(request, [], [])
    fallback.score_many.assert_not_awaited()


def test_fallback_scorer_uses_fallback_and_adds_unique_warning() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    warning = (
        "Primary relevance scorer failed (RuntimeError); "
        "rule-based fallback was used"
    )
    fallback_result = PaperRelevanceResult(warnings=[warning])
    primary = AsyncMock(spec=PaperRelevanceScorer)
    primary.score_many.side_effect = RuntimeError("Qwen unavailable")
    fallback = AsyncMock(spec=PaperRelevanceScorer)
    fallback.score_many.return_value = fallback_result
    scorer = FallbackPaperRelevanceScorer(primary, fallback)

    result = asyncio.run(scorer.score_many(request, [], []))

    assert result.assessments == fallback_result.assessments
    assert result.warnings == [warning]
    fallback.score_many.assert_awaited_once_with(request, [], [])


def test_fallback_scorer_propagates_cancellation() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    primary = AsyncMock(spec=PaperRelevanceScorer)
    primary.score_many.side_effect = asyncio.CancelledError()
    fallback = AsyncMock(spec=PaperRelevanceScorer)
    scorer = FallbackPaperRelevanceScorer(primary, fallback)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scorer.score_many(request, [], []))

    fallback.score_many.assert_not_awaited()


def test_shortlisting_scorer_rejects_invalid_limit() -> None:
    scorer = AsyncMock(spec=PaperRelevanceScorer)

    with pytest.raises(ValueError, match="at least 1"):
        ShortlistingPaperRelevanceScorer(scorer, scorer, 0)


def test_shortlisting_scorer_returns_empty_without_calling_scorers() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    prefilter = AsyncMock(spec=PaperRelevanceScorer)
    shortlist = AsyncMock(spec=PaperRelevanceScorer)
    scorer = ShortlistingPaperRelevanceScorer(prefilter, shortlist, 2)

    result = asyncio.run(scorer.score_many(request, [], []))

    assert result == PaperRelevanceResult()
    prefilter.score_many.assert_not_awaited()
    shortlist.score_many.assert_not_awaited()


def test_shortlisting_scorer_sends_small_input_directly() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    candidate = PaperSearchResult(
        source="openalex",
        source_id="W1",
        title="Graph Learning",
    )
    expected = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source="openalex",
                source_id="W1",
                score=0.9,
            )
        ]
    )
    prefilter = AsyncMock(spec=PaperRelevanceScorer)
    shortlist = AsyncMock(spec=PaperRelevanceScorer)
    shortlist.score_many.return_value = expected
    scorer = ShortlistingPaperRelevanceScorer(prefilter, shortlist, 2)

    result = asyncio.run(
        scorer.score_many(request, ["graph learning"], [candidate])
    )

    assert result is expected
    prefilter.score_many.assert_not_awaited()
    shortlist.score_many.assert_awaited_once_with(
        request,
        ["graph learning"],
        [candidate],
    )


def test_shortlisting_scorer_ranks_merges_and_preserves_order() -> None:
    request = SearchRequest(
        topic="graph learning",
        description="Find graph learning work",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    low = PaperSearchResult(
        source="openalex",
        source_id="low",
        title="Low relevance",
        cited_by_count=100,
    )
    high_low_citations = PaperSearchResult(
        source="openalex",
        source_id="high-low-citations",
        title="High relevance A",
        cited_by_count=10,
    )
    high_high_citations = PaperSearchResult(
        source="openalex",
        source_id="high-high-citations",
        title="High relevance B",
        cited_by_count=20,
    )
    papers = [low, high_low_citations, high_high_citations]
    prefilter = AsyncMock(spec=PaperRelevanceScorer)
    prefilter.score_many.return_value = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source="openalex",
                source_id="low",
                score=0.2,
                reason="rule-low",
            ),
            PaperRelevanceAssessment(
                source="openalex",
                source_id="high-low-citations",
                score=0.8,
                reason="rule-a",
            ),
            PaperRelevanceAssessment(
                source="openalex",
                source_id="high-high-citations",
                score=0.8,
                reason="rule-b",
            ),
        ],
        warnings=["prefilter warning", "shared warning"],
    )
    shortlist = AsyncMock(spec=PaperRelevanceScorer)
    shortlist.score_many.return_value = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source="openalex",
                source_id="high-high-citations",
                score=0.6,
                reason="semantic-b",
            ),
            PaperRelevanceAssessment(
                source="openalex",
                source_id="high-low-citations",
                score=0.95,
                reason="semantic-a",
            ),
        ],
        warnings=["shared warning", "semantic warning"],
    )
    scorer = ShortlistingPaperRelevanceScorer(prefilter, shortlist, 2)

    result = asyncio.run(
        scorer.score_many(request, ["graph learning"], papers)
    )

    shortlist.score_many.assert_awaited_once_with(
        request,
        ["graph learning"],
        [high_high_citations, high_low_citations],
    )
    assert [item.source_id for item in result.assessments] == [
        "low",
        "high-low-citations",
        "high-high-citations",
    ]
    assert [item.score for item in result.assessments] == [0.2, 0.95, 0.6]
    assert [item.reason for item in result.assessments] == [
        "rule-low",
        "semantic-a",
        "semantic-b",
    ]
    assert result.warnings == [
        "prefilter warning",
        "shared warning",
        "semantic warning",
    ]
