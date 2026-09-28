import asyncio
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.repositories.paper import PaperRepository
from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader


def make_paper(paper_id: int) -> Paper:
    return Paper(
        id=paper_id,
        source="openalex",
        source_id=f"W{paper_id}",
        title=f"Paper {paper_id}",
        authors=[f"Author {paper_id}"],
        doi=f"10.1000/{paper_id}",
        abstract=f"Abstract {paper_id}",
        landing_page_url=f"https://example.test/papers/{paper_id}",
        pdf_url=f"https://example.test/papers/{paper_id}.pdf",
    )


def make_loader() -> tuple[
    SelectedPaperCodeInputLoader,
    AsyncMock,
    AsyncMock,
]:
    paper_repository = AsyncMock(spec=PaperRepository)
    run_repository = AsyncMock(spec=LiteratureRunRepository)
    return (
        SelectedPaperCodeInputLoader(
            paper_repository=paper_repository,
            literature_run_repository=run_repository,
        ),
        paper_repository,
        run_repository,
    )


def test_loader_preserves_selection_order_and_merges_method_profile() -> None:
    loader, paper_repository, run_repository = make_loader()
    profile = PaperMethodProfile(
        source="openalex",
        source_id="W2",
        research_problem="Graph oversmoothing",
        core_method="Adaptive propagation",
        confidence=0.9,
    )
    run_repository.get_run_papers.return_value = [
        LiteratureRunPaper(paper_id=1, position=0),
        LiteratureRunPaper(paper_id=2, position=1, method_profile=profile),
    ]
    paper_repository.get_by_ids.return_value = [make_paper(1), make_paper(2)]

    result = asyncio.run(loader.load(7, [2, 1]))

    assert [paper.paper_id for paper in result] == [2, 1]
    assert result[0].source_id == "W2"
    assert result[0].authors == ["Author 2"]
    assert result[0].doi == "10.1000/2"
    assert result[0].abstract == "Abstract 2"
    assert result[0].landing_page_url == "https://example.test/papers/2"
    assert result[0].pdf_url == "https://example.test/papers/2.pdf"
    assert result[0].method_profile == profile
    assert result[1].method_profile is None
    run_repository.get_run_papers.assert_awaited_once_with(7)
    paper_repository.get_by_ids.assert_awaited_once_with([2, 1])


def test_loader_allows_paper_without_run_metadata() -> None:
    loader, paper_repository, run_repository = make_loader()
    run_repository.get_run_papers.return_value = []
    paper_repository.get_by_ids.return_value = [make_paper(3)]

    result = asyncio.run(loader.load(7, [3]))

    assert result[0].paper_id == 3
    assert result[0].method_profile is None


def test_loader_reports_all_missing_selected_papers() -> None:
    loader, paper_repository, run_repository = make_loader()
    run_repository.get_run_papers.return_value = []
    paper_repository.get_by_ids.return_value = [make_paper(2)]

    with pytest.raises(ValueError, match=r"missing paper ids: \[3, 4\]"):
        asyncio.run(loader.load(7, [2, 3, 4]))
