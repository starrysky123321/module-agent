import asyncio
import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai import AsyncOpenAI

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.method import (
    PaperEvidence,
    PaperMethodExtractionResult,
    PaperMethodProfile,
)
from module_agent.literature.adapters.llm.qwen_method_extractor import (
    MAX_QWEN_PROFILE_PAPERS,
    SYSTEM_PROMPT,
    QwenPaperMethodExtractor,
    QwenMethodResponse,
)


def search_request() -> SearchRequest:
    return SearchRequest(
        topic="图神经网络过平滑",
        description="寻找可复用的缓解过平滑算法模块",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=["oversmoothing"],
        max_results=10,
    )


def paper(source_id: str = "W123") -> PaperSearchResult:
    return PaperSearchResult(
        source="openalex",
        source_id=source_id,
        title="Mitigating Oversmoothing in Graph Neural Networks",
        abstract=(
            "We propose an adaptive propagation module to preserve node "
            "feature diversity and mitigate oversmoothing."
        ),
        doi="10.1000/example",
        is_open_access=True,
    )


def client_with_result(
    parsed: PaperMethodExtractionResult | None,
) -> tuple[MagicMock, AsyncMock]:
    parse = AsyncMock()
    parse.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(parsed=parsed))]
    )
    client = MagicMock(spec=AsyncOpenAI)
    client.chat.completions.parse = parse
    return client, parse


def test_extractor_normalizes_and_validates_model_name() -> None:
    client, _ = client_with_result(None)

    extractor = QwenPaperMethodExtractor(client, "  qwen3.7-plus  ")

    assert extractor.model == "qwen3.7-plus"
    with pytest.raises(ValueError, match="model"):
        QwenPaperMethodExtractor(client, "   ")


def test_extractor_returns_empty_without_qwen_call() -> None:
    client, parse = client_with_result(None)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    result = asyncio.run(extractor.extract_many(search_request(), []))

    assert result == PaperMethodExtractionResult()
    parse.assert_not_awaited()


def test_extractor_returns_grounded_structured_profiles() -> None:
    candidate = paper()
    profile = PaperMethodProfile(
        source=candidate.source,
        source_id=candidate.source_id,
        research_problem="Oversmoothing in graph neural networks",
        module_type="adaptive propagation module",
        core_method="preserves node feature diversity",
        inputs=["node features"],
        outputs=[],
        applicable_tasks=[],
        evidence=[
            PaperEvidence(
                field="title",
                excerpt="Mitigating Oversmoothing",
            ),
            PaperEvidence(
                field="abstract",
                excerpt="adaptive propagation module",
            ),
        ],
        confidence=0.9,
    )
    parsed = PaperMethodExtractionResult(
        profiles=[profile],
        warnings=["untrusted model warning"],
    )
    client, parse = client_with_result(parsed)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    result = asyncio.run(
        extractor.extract_many(search_request(), [candidate])
    )

    assert result.profiles == [profile]
    assert result.warnings == []
    call = parse.await_args.kwargs
    assert call["model"] == "qwen3.7-plus"
    assert call["response_format"] is QwenMethodResponse
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
            "abstract": candidate.abstract,
        }
    ]
    assert "doi" not in payload["papers"][0]
    assert "is_open_access" not in payload["papers"][0]


def test_extractor_rejects_more_than_ten_papers_without_call() -> None:
    client, parse = client_with_result(None)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")
    papers = [
        paper(str(index)) for index in range(MAX_QWEN_PROFILE_PAPERS + 1)
    ]

    with pytest.raises(ValueError, match="at most 10 papers"):
        asyncio.run(extractor.extract_many(search_request(), papers))

    parse.assert_not_awaited()


def test_extractor_rejects_duplicate_input_identities_without_call() -> None:
    client, parse = client_with_result(None)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="duplicate identities"):
        asyncio.run(
            extractor.extract_many(search_request(), [paper(), paper()])
        )

    parse.assert_not_awaited()


def test_extractor_rejects_missing_parsed_result() -> None:
    client, _ = client_with_result(None)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="no parsed method extraction result"):
        asyncio.run(extractor.extract_many(search_request(), [paper()]))


@pytest.mark.parametrize(
    "profiles",
    [
        [],
        [
            PaperMethodProfile(
                source="openalex",
                source_id="invented",
                confidence=0.0,
            )
        ],
        [
            PaperMethodProfile(
                source="openalex",
                source_id="W123",
                confidence=0.0,
            ),
            PaperMethodProfile(
                source="openalex",
                source_id="W123",
                confidence=0.0,
            ),
        ],
    ],
)
def test_extractor_rejects_missing_unknown_or_duplicate_profile_ids(
    profiles: list[PaperMethodProfile],
) -> None:
    client, _ = client_with_result(
        PaperMethodExtractionResult(profiles=profiles)
    )
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="do not match input papers"):
        asyncio.run(extractor.extract_many(search_request(), [paper()]))


def test_extractor_rejects_claims_without_evidence() -> None:
    parsed = PaperMethodExtractionResult(
        profiles=[
            PaperMethodProfile(
                source="openalex",
                source_id="W123",
                core_method="adaptive propagation",
                confidence=0.8,
            )
        ]
    )
    client, _ = client_with_result(parsed)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="claims without paper evidence"):
        asyncio.run(extractor.extract_many(search_request(), [paper()]))


@pytest.mark.parametrize(
    ("field", "excerpt"),
    [
        ("abstract", "not stated by this paper"),
        ("title", "adaptive propagation module"),
        ("abstract", "   "),
    ],
)
def test_extractor_rejects_unverifiable_evidence(
    field: str,
    excerpt: str,
) -> None:
    parsed = PaperMethodExtractionResult(
        profiles=[
            PaperMethodProfile(
                source="openalex",
                source_id="W123",
                core_method="adaptive propagation",
                evidence=[
                    PaperEvidence(field=field, excerpt=excerpt)
                ],
                confidence=0.8,
            )
        ]
    )
    client, _ = client_with_result(parsed)
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    with pytest.raises(ValueError, match="not in the paper metadata"):
        asyncio.run(extractor.extract_many(search_request(), [paper()]))
