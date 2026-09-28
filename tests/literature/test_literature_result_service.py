import asyncio
from unittest.mock import AsyncMock

import pytest

from module_agent.shared.exceptions import LiteratureRunNotFoundError
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.literature.domain.repositories.paper import PaperRepository
from module_agent.literature.application.result import LiteratureResultService


def test_result_service_returns_papers_in_repository_order() -> None:
    profile = PaperMethodProfile(
        source="openalex", source_id="W20", module_type="encoder", confidence=0.8
    )
    run_repository = AsyncMock(spec=LiteratureRunRepository)
    run_repository.get_by_id.return_value = object()
    run_repository.get_run_papers.return_value = [
        LiteratureRunPaper(
            paper_id=20,
            position=0,
            relevance_score=0.9,
            relevance_reason="Direct match",
            matched_terms=["graph"],
            method_profile=profile,
        ),
        LiteratureRunPaper(
            paper_id=10,
            position=1,
            relevance_score=0.6,
            relevance_reason="Partial match",
        ),
    ]
    papers = [
        Paper(
            id=20,
            source="openalex",
            source_id="W20",
            title="Second Paper",
            authors=[],
        ),
        Paper(
            id=10,
            source="openalex",
            source_id="W10",
            title="First Paper",
            authors=[],
        ),
    ]
    paper_repository = AsyncMock(spec=PaperRepository)
    paper_repository.get_by_ids.return_value = papers
    service = LiteratureResultService(
        paper_repository=paper_repository,
        run_repository=run_repository,
    )

    result = asyncio.run(service.get_papers(3))

    assert [item.id for item in result] == [20, 10]
    assert result[0].position == 0
    assert result[0].relevance_score == 0.9
    assert result[0].relevance_reason == "Direct match"
    assert result[0].matched_terms == ["graph"]
    assert result[0].method_profile == profile
    assert result[1].position == 1
    assert result[1].relevance_score == 0.6
    assert result[1].method_profile is None
    run_repository.get_by_id.assert_awaited_once_with(3)
    run_repository.get_run_papers.assert_awaited_once_with(3)
    paper_repository.get_by_ids.assert_awaited_once_with([20, 10])


def test_result_service_rejects_unknown_run_without_querying_papers() -> None:
    run_repository = AsyncMock(spec=LiteratureRunRepository)
    run_repository.get_by_id.return_value = None
    paper_repository = AsyncMock(spec=PaperRepository)
    service = LiteratureResultService(
        paper_repository=paper_repository,
        run_repository=run_repository,
    )

    with pytest.raises(LiteratureRunNotFoundError, match="Run with id 99 not found"):
        asyncio.run(service.get_papers(99))

    run_repository.get_run_papers.assert_not_awaited()
    paper_repository.get_by_ids.assert_not_awaited()
