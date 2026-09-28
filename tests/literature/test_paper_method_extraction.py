import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.search import PaperSearchResult, SearchRequest
from module_agent.literature.domain.method import (
    PaperMethodExtractionResult,
    PaperMethodExtractor,
    PaperMethodProfile,
)
from module_agent.literature.application.method_extraction import (
    BatchedPaperMethodExtractor,
    FallbackPaperMethodExtractor,
)


def request() -> SearchRequest:
    return SearchRequest(
        topic="GNN oversmoothing",
        description="Find reusable algorithm modules",
        start_date=date(2024, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=[],
        max_results=10,
    )


def paper(source_id: str = "W123") -> PaperSearchResult:
    return PaperSearchResult(
        source="openalex",
        source_id=source_id,
        title="Example Paper",
    )


def test_fallback_extractor_returns_empty_without_primary_call() -> None:
    primary = AsyncMock(spec=PaperMethodExtractor)
    extractor = FallbackPaperMethodExtractor(primary)

    result = asyncio.run(extractor.extract_many(request(), []))

    assert result == PaperMethodExtractionResult()
    primary.extract_many.assert_not_awaited()


def test_fallback_extractor_preserves_successful_primary_result() -> None:
    candidate = paper()
    expected = PaperMethodExtractionResult(
        profiles=[
            PaperMethodProfile(
                source=candidate.source,
                source_id=candidate.source_id,
                research_problem="GNN oversmoothing",
                confidence=0.9,
            )
        ]
    )
    primary = AsyncMock(spec=PaperMethodExtractor)
    primary.extract_many.return_value = expected
    extractor = FallbackPaperMethodExtractor(primary)

    result = asyncio.run(
        extractor.extract_many(request(), [candidate])
    )

    assert result is expected
    primary.extract_many.assert_awaited_once()


def test_fallback_extractor_returns_unknown_profile_with_warning() -> None:
    candidates = [paper("W123"), paper("W124")]
    primary = AsyncMock(spec=PaperMethodExtractor)
    primary.extract_many.side_effect = RuntimeError("Qwen unavailable")
    extractor = FallbackPaperMethodExtractor(primary)

    result = asyncio.run(extractor.extract_many(request(), candidates))

    assert [(item.source, item.source_id) for item in result.profiles] == [
        ("openalex", "W123"),
        ("openalex", "W124"),
    ]
    assert all(item.confidence == 0.0 for item in result.profiles)
    assert all(item.research_problem is None for item in result.profiles)
    assert all(item.module_type is None for item in result.profiles)
    assert all(item.core_method is None for item in result.profiles)
    assert result.warnings == [
        "Paper method extraction failed (RuntimeError); "
        "unknown profiles were used"
    ]


def test_fallback_extractor_propagates_cancellation() -> None:
    primary = AsyncMock(spec=PaperMethodExtractor)
    primary.extract_many.side_effect = asyncio.CancelledError()
    extractor = FallbackPaperMethodExtractor(primary)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(extractor.extract_many(request(), [paper()]))


@pytest.mark.parametrize("batch_size", [0, -1, 11])
def test_batched_extractor_rejects_invalid_batch_size(
    batch_size: int,
) -> None:
    inner = AsyncMock(spec=PaperMethodExtractor)

    with pytest.raises(ValueError, match="Batch size"):
        BatchedPaperMethodExtractor(inner, batch_size=batch_size)


def test_batched_extractor_returns_empty_without_inner_call() -> None:
    inner = AsyncMock(spec=PaperMethodExtractor)
    extractor = BatchedPaperMethodExtractor(inner)

    result = asyncio.run(extractor.extract_many(request(), []))

    assert result == PaperMethodExtractionResult()
    inner.extract_many.assert_not_awaited()


def test_batched_extractor_splits_reorders_and_deduplicates_warnings() -> None:
    candidates = [paper(f"W{index}") for index in range(23)]
    inner = AsyncMock(spec=PaperMethodExtractor)
    batches: list[list[str]] = []

    async def return_profiles(
        _: SearchRequest,
        batch: list[PaperSearchResult],
    ) -> PaperMethodExtractionResult:
        batches.append([item.source_id for item in batch])
        profiles = [
            PaperMethodProfile(
                source=item.source,
                source_id=item.source_id,
                confidence=0.0,
            )
            for item in reversed(batch)
        ]
        return PaperMethodExtractionResult(
            profiles=profiles,
            warnings=["shared warning", f"batch {len(batches)} warning"],
        )

    inner.extract_many.side_effect = return_profiles
    extractor = BatchedPaperMethodExtractor(inner, batch_size=10)

    result = asyncio.run(
        extractor.extract_many(request(), candidates)
    )

    assert [len(batch) for batch in batches] == [10, 10, 3]
    assert [item.source_id for item in result.profiles] == [
        item.source_id for item in candidates
    ]
    assert result.warnings == [
        "shared warning",
        "batch 1 warning",
        "batch 2 warning",
        "batch 3 warning",
    ]


def test_batched_extractor_propagates_inner_error() -> None:
    inner = AsyncMock(spec=PaperMethodExtractor)
    inner.extract_many.side_effect = RuntimeError("inner failed")
    extractor = BatchedPaperMethodExtractor(inner)

    with pytest.raises(RuntimeError, match="inner failed"):
        asyncio.run(extractor.extract_many(request(), [paper()]))


@pytest.mark.parametrize(
    "profiles",
    [
        [],
        [
            PaperMethodProfile(
                source="openalex",
                source_id="unknown",
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
def test_batched_extractor_rejects_invalid_inner_profiles(
    profiles: list[PaperMethodProfile],
) -> None:
    inner = AsyncMock(spec=PaperMethodExtractor)
    inner.extract_many.return_value = PaperMethodExtractionResult(
        profiles=profiles
    )
    extractor = BatchedPaperMethodExtractor(inner)

    with pytest.raises(ValueError, match="do not match batch papers"):
        asyncio.run(extractor.extract_many(request(), [paper()]))
