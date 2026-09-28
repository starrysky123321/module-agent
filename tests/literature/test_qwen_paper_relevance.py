import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.ranking import (
    PaperRelevanceAssessment,
    PaperRelevanceResult,
)
from module_agent.literature.domain.llm_metric import LlmCallMetric, LlmCallOutcome
from module_agent.literature.adapters.llm.qwen_relevance import (
    MAX_QWEN_RELEVANCE_PAPERS,
    SYSTEM_PROMPT,
    QwenPaperRelevanceScorer,
    QwenRelevanceResponse,
)


def search_request() -> SearchRequest:
    return SearchRequest(
        topic="图神经网络过平滑",
        description="寻找直接缓解图神经网络过平滑问题的方法",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=["oversmoothing"],
        max_results=10,
    )


def paper(source_id: str = "W123") -> PaperSearchResult:
    return PaperSearchResult(
        source="openalex",
        source_id=source_id,
        title="Addressing Oversmoothing in Graph Neural Networks",
        abstract="A method that directly mitigates oversmoothing.",
    )


def qwen_client_with_parsed_result(
    parsed: PaperRelevanceResult | None,
) -> tuple[MagicMock, AsyncMock]:
    parse = AsyncMock()
    parse.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(parsed=parsed))]
    )
    client = MagicMock(spec=AsyncOpenAI)
    client.chat.completions.parse = parse
    return client, parse


def test_qwen_relevance_scorer_normalizes_model_name() -> None:
    client, _ = qwen_client_with_parsed_result(None)

    scorer = QwenPaperRelevanceScorer(client, "  qwen3.7-plus  ")

    assert scorer.model == "qwen3.7-plus"
    with pytest.raises(ValueError, match="model"):
        QwenPaperRelevanceScorer(client, "   ")


def test_qwen_relevance_scorer_skips_api_for_empty_papers() -> None:
    client, parse = qwen_client_with_parsed_result(None)
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")

    result = asyncio.run(scorer.score_many(search_request(), [], []))

    assert result == PaperRelevanceResult()
    parse.assert_not_awaited()


def test_qwen_relevance_scorer_returns_validated_result() -> None:
    candidate = paper()
    parsed = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source=candidate.source,
                source_id=candidate.source_id,
                score=0.95,
                matched_terms=["oversmoothing"],
                reason="Directly addresses the requested problem.",
            )
        ],
        warnings=["untrusted model warning"],
        llm_metrics=[
            LlmCallMetric(
                stage="relevance_scoring",
                model="fake-model-metric",
                item_count=21,
                duration_ms=20200.0,
                timeout_seconds=180.0,
                outcome=LlmCallOutcome.SUCCESS,
            )
        ],
    )
    client, parse = qwen_client_with_parsed_result(parsed)
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")

    result = asyncio.run(
        scorer.score_many(
            search_request(),
            ["graph neural network oversmoothing mitigation"],
            [candidate],
        )
    )

    assert result.assessments == parsed.assessments
    assert result.warnings == []
    assert result.llm_metrics == []
    call = parse.await_args.kwargs
    assert call["model"] == "qwen3.7-plus"
    assert call["response_format"] is QwenRelevanceResponse
    assert call["messages"][0] == {
        "role": "system",
        "content": SYSTEM_PROMPT,
    }
    payload = json.loads(call["messages"][1]["content"])
    assert payload["request"]["topic"] == "图神经网络过平滑"
    assert payload["papers"] == [
        {
            "source": "openalex",
            "source_id": "W123",
            "title": candidate.title,
            "publication_type": None,
            "abstract": candidate.abstract,
        }
    ]


def test_qwen_relevance_scorer_rejects_too_many_papers() -> None:
    client, parse = qwen_client_with_parsed_result(None)
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")
    papers = [
        paper(str(index))
        for index in range(MAX_QWEN_RELEVANCE_PAPERS + 1)
    ]

    with pytest.raises(ValueError, match="at most 20 papers"):
        asyncio.run(scorer.score_many(search_request(), [], papers))

    parse.assert_not_awaited()


def test_qwen_relevance_scorer_rejects_missing_parsed_result() -> None:
    client, _ = qwen_client_with_parsed_result(None)
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="no parsed relevance result"):
        asyncio.run(scorer.score_many(search_request(), [], [paper()]))


@pytest.mark.parametrize("returned_source_id", ["unknown", "W124"])
def test_qwen_relevance_scorer_rejects_mismatched_paper_identity(
    returned_source_id: str,
) -> None:
    parsed = PaperRelevanceResult(
        assessments=[
            PaperRelevanceAssessment(
                source="openalex",
                source_id=returned_source_id,
                score=0.5,
            )
        ]
    )
    client, _ = qwen_client_with_parsed_result(parsed)
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="does not match input papers"):
        asyncio.run(scorer.score_many(search_request(), [], [paper()]))


def test_qwen_relevance_scorer_rejects_missing_assessment() -> None:
    client, _ = qwen_client_with_parsed_result(PaperRelevanceResult())
    scorer = QwenPaperRelevanceScorer(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="does not match input papers"):
        asyncio.run(scorer.score_many(search_request(), [], [paper()]))
