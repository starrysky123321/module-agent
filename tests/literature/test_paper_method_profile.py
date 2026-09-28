import asyncio
from collections.abc import Sequence
from datetime import date

import pytest
from pydantic import ValidationError

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.method import (
    PaperEvidence,
    PaperMethodExtractionResult,
    PaperMethodExtractor,
    PaperMethodProfile,
)


def test_method_profile_preserves_evidence_and_safe_defaults() -> None:
    profile = PaperMethodProfile(
        source="openalex",
        source_id="W123",
        research_problem="Oversmoothing in deep GNNs",
        evidence=[
            PaperEvidence(
                field="abstract",
                excerpt="directly mitigates oversmoothing",
            )
        ],
        confidence=0.85,
    )

    assert profile.module_type is None
    assert profile.core_method is None
    assert profile.inputs == []
    assert profile.outputs == []
    assert profile.applicable_tasks == []
    assert profile.evidence[0].field == "abstract"


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_method_profile_rejects_confidence_outside_unit_interval(
    confidence: float,
) -> None:
    with pytest.raises(ValidationError):
        PaperMethodProfile(
            source="openalex",
            source_id="W123",
            confidence=confidence,
        )


def test_evidence_rejects_unsupported_source_field() -> None:
    with pytest.raises(ValidationError):
        PaperEvidence(field="paper_body", excerpt="example")


def test_method_extractor_protocol_returns_structured_result() -> None:
    class ExampleExtractor:
        async def extract_many(
            self,
            request: SearchRequest,
            papers: Sequence[PaperSearchResult],
        ) -> PaperMethodExtractionResult:
            return PaperMethodExtractionResult(
                profiles=[
                    PaperMethodProfile(
                        source=paper.source,
                        source_id=paper.source_id,
                        confidence=0.0,
                    )
                    for paper in papers
                ]
            )

    extractor: PaperMethodExtractor = ExampleExtractor()
    request = SearchRequest(
        topic="GNN oversmoothing",
        description="Find reusable modules",
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=[],
        max_results=10,
    )
    paper = PaperSearchResult(
        source="openalex",
        source_id="W123",
        title="Example Paper",
    )

    result = asyncio.run(extractor.extract_many(request, [paper]))

    assert result.profiles[0].source_id == "W123"
    assert result.profiles[0].confidence == 0.0
    assert result.warnings == []
