import asyncio

import httpx
import pytest

from module_agent.literature.adapters.sources.crossref_integrity import (
    CrossrefPaperIntegrityChecker,
)
from module_agent.literature.adapters.sources.openalex import parse_work
from module_agent.literature.application.deduplication import deduplicate_papers
from module_agent.literature.application.integrity import PaperIntegrityService
from module_agent.literature.domain.integrity import (
    PaperIntegrity,
    PaperIntegrityStatus,
    title_integrity,
)
from module_agent.literature.domain.search import PaperSearchResult


def test_openalex_retraction_flag_is_not_ignored() -> None:
    paper = parse_work({"id": "W1", "title": "Normal title", "is_retracted": True})
    assert paper.integrity and paper.integrity.blocked


def test_deduplication_keeps_retraction_from_less_complete_record() -> None:
    rich = PaperSearchResult(
        source="openalex",
        source_id="W1",
        title="Example",
        abstract="Detailed",
        doi="10.1000/test",
    )
    flagged = PaperSearchResult(
        source="other",
        source_id="2",
        title="Example",
        integrity=PaperIntegrity(status=PaperIntegrityStatus.RETRACTED),
    )
    result = deduplicate_papers([rich, flagged])
    assert len(result) == 1 and result[0].integrity and result[0].integrity.blocked


def test_papers_about_retraction_are_not_assumed_retracted() -> None:
    assert title_integrity("Retraction rates in science", "crossref") is None
    assert (
        title_integrity("Retraction: an old paper", "crossref").status
        == PaperIntegrityStatus.NOTICE
    )


@pytest.mark.parametrize(
    "title,status",
    [
        ("Retracted: Handwritten Digit Recognition", PaperIntegrityStatus.RETRACTED),
        (
            "<i>RETRACTED:</i> Handwritten Digit Recognition",
            PaperIntegrityStatus.RETRACTED,
        ),
        ("Retraction Note: Old work", PaperIntegrityStatus.NOTICE),
        ("Normal work", PaperIntegrityStatus.NOT_FLAGGED),
    ],
)
def test_crossref_title_is_used_even_if_source_title_omitted_marker(
    title, status
) -> None:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"message": {"DOI": "10.1000/test", "title": [title]}}
                )
            )
        ) as client:
            return await CrossrefPaperIntegrityChecker(client).check(
                "10.1000/test", "Original title"
            )

    assert asyncio.run(run()).status == status


@pytest.mark.parametrize("http_status", [404, 429, 500])
def test_registry_failure_never_becomes_not_flagged(http_status) -> None:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(http_status))
        ) as client:
            return await CrossrefPaperIntegrityChecker(client).check(
                "10.1000/test", "Title"
            )

    result = asyncio.run(run())
    assert result.status == PaperIntegrityStatus.UNKNOWN and result.warnings


def test_crossref_response_for_other_doi_does_not_count_as_verified() -> None:
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"message": {"DOI": "10.1000/other", "title": ["Other"]}}
                )
            )
        ) as client:
            return await CrossrefPaperIntegrityChecker(client).check(
                "10.1000/test", "Title"
            )

    assert asyncio.run(run()).status == PaperIntegrityStatus.UNKNOWN


def test_batch_deadline_cancels_slow_checks_and_preserves_unknown() -> None:
    cancelled = []

    class SlowChecker:
        async def check(self, doi, title):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.append(title)

    async def run():
        papers = [
            PaperSearchResult(source="test", source_id=str(i), title=f"Paper {i}")
            for i in range(4)
        ]
        return await PaperIntegrityService(
            SlowChecker(), budget_seconds=0.02
        ).check_many(papers)

    papers, warnings = asyncio.run(run())
    assert len(papers) == 4 and warnings and len(cancelled) == 2
    assert all(p.integrity.status == PaperIntegrityStatus.UNKNOWN for p in papers)


def test_batch_filters_retracted_and_keeps_other_results() -> None:
    class Checker:
        async def check(self, doi, title):
            return PaperIntegrity(
                status=PaperIntegrityStatus.RETRACTED
                if title == "Bad"
                else PaperIntegrityStatus.NOT_FLAGGED
            )

    async def run():
        papers = [
            PaperSearchResult(source="test", source_id=title, title=title)
            for title in ("Bad", "Good")
        ]
        return await PaperIntegrityService(Checker()).check_many(papers)

    papers, warnings = asyncio.run(run())
    assert [p.title for p in papers] == ["Good"] and any(
        "已排除" in w for w in warnings
    )
