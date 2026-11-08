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
    parsed: PaperMethodExtractionResult | QwenMethodResponse | None,
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
def test_extractor_downgrades_missing_unknown_or_duplicate_profile_ids(
    profiles: list[PaperMethodProfile],
) -> None:
    client, _ = client_with_result(
        PaperMethodExtractionResult(profiles=profiles)
    )
    extractor = QwenPaperMethodExtractor(client, "qwen3.7-plus")

    result = asyncio.run(extractor.extract_many(search_request(), [paper()]))

    assert len(result.profiles) == 1
    assert result.profiles[0].source_id == "W123"
    assert result.profiles[0].confidence == 0
    assert any(issue.code in {"missing_profile", "duplicate_profile"} for issue in result.issues)
    assert all("W123" in issue.as_warning() for issue in result.issues if issue.fallback)


def test_extractor_downgrades_claims_without_evidence() -> None:
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

    result = asyncio.run(extractor.extract_many(search_request(), [paper()]))

    assert result.profiles[0].confidence == 0
    assert result.issues[0].code == "claims_without_evidence"
    assert "claims without paper evidence" in result.warnings[0]
    assert "W123" in result.warnings[0]


@pytest.mark.parametrize(
    ("field", "excerpt"),
    [
        ("abstract", "not stated by this paper"),
        ("title", "adaptive propagation module"),
        ("abstract", "   "),
    ],
)
def test_extractor_downgrades_unverifiable_evidence(
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

    result = asyncio.run(extractor.extract_many(search_request(), [paper()]))

    assert result.profiles[0].confidence == 0
    assert result.issues[0].code == "evidence_not_in_metadata"
    assert result.issues[0].evidence_field == field
    assert "not in the paper metadata" in result.warnings[0]
    assert "W123" in result.warnings[0]


def grounded_profile(candidate: PaperSearchResult) -> dict:
    return {
        "source": candidate.source, "source_id": candidate.source_id,
        "core_method": "adaptive propagation module", "confidence": 0.9,
        "evidence": [{"field": "abstract", "excerpt": "adaptive propagation module"}],
    }


@pytest.mark.parametrize("fault", ["evidence", "schema", "missing", "duplicate"])
def test_one_bad_profile_preserves_other_grounded_profiles_and_input_order(fault: str) -> None:
    candidates = [paper("W1"), paper("W2"), paper("W3")]
    raw = [grounded_profile(candidate) for candidate in reversed(candidates)]
    if fault == "evidence":
        raw[1]["evidence"] = [{"field": "abstract", "excerpt": "invented algorithm"}]
    elif fault == "schema":
        raw[1]["confidence"] = "not-a-confidence"
    elif fault == "missing":
        raw.pop(1)
    else:
        raw.append(raw[1].copy())
    # The SDK envelope must accept an individual malformed item for local validation.
    parsed = QwenMethodResponse.model_validate({"profiles": raw})
    client, parse = client_with_result(parsed)
    result = asyncio.run(QwenPaperMethodExtractor(client, "qwen-test").extract_many(search_request(), candidates))

    parse.assert_awaited_once()
    assert [profile.source_id for profile in result.profiles] == ["W1", "W2", "W3"]
    assert [profile.confidence for profile in result.profiles] == [0.9, 0.0, 0.9]
    assert result.profiles[0].evidence
    assert result.profiles[2].evidence
    assert len(result.issues) == 1
    assert result.issues[0].source_id == "W2"
    assert "W2" in result.warnings[0]


def test_schema_failure_logs_field_and_identity_without_raw_model_content(method_logs: list[str]) -> None:
    raw = grounded_profile(paper())
    raw["confidence"] = "api_key=DO-NOT-LOG-THIS"
    parsed = QwenMethodResponse.model_validate({"profiles": [raw]})
    client, _ = client_with_result(parsed)
    result = asyncio.run(QwenPaperMethodExtractor(client, "qwen-test").extract_many(search_request(), [paper()]))

    logs = "".join(method_logs)
    assert "W123" in logs
    assert "invalid_profile_schema" in logs
    assert "confidence: float_parsing" in result.issues[0].message
    assert "DO-NOT-LOG-THIS" not in logs + json.dumps(result.model_dump())


def test_unknown_extra_profile_does_not_replace_a_valid_input_profile() -> None:
    extra = grounded_profile(paper("unrequested"))
    client, _ = client_with_result(QwenMethodResponse.model_validate({
        "profiles": [extra, grounded_profile(paper())],
    }))
    result = asyncio.run(QwenPaperMethodExtractor(client, "qwen-test").extract_many(search_request(), [paper()]))

    assert result.profiles[0].confidence == 0.9
    assert result.issues[0].code == "unexpected_profile"
    assert result.issues[0].fallback is False


def test_skip_validation_preserves_provider_schema_constraints() -> None:
    schema = QwenMethodResponse.model_json_schema()
    text = json.dumps(schema)
    assert '"maximum": 1.0' in text
    assert '"minimum": 0.0' in text
    assert '"abstract"' in text
