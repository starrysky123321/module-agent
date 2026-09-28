import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock

import pytest

from module_agent.shared.exceptions import (
    InvalidPaperSelectionError,
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
    PaperSelectionAlreadyExistsError,
)
from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.selection import PaperSelection
from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.literature.domain.repositories.selection import PaperSelectionRepository
from module_agent.workflow.domain import PaperSelectionRequest
from module_agent.literature.application.selection import PaperSelectionService


def _run(status: LiteratureRunStatus) -> LiteratureRun:
    return LiteratureRun(
        id=7,
        status=status,
        request=SearchRequest(
            topic="graph neural networks",
            description="Find representative papers",
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            keywords=["GNN"],
            max_results=10,
        ),
    )


def _service() -> tuple[PaperSelectionService, AsyncMock, AsyncMock]:
    run_repository = AsyncMock(spec=LiteratureRunRepository)
    selection_repository = AsyncMock(spec=PaperSelectionRepository)
    selection_repository.get_by_run_id.return_value = None
    return (
        PaperSelectionService(run_repository, selection_repository),
        run_repository,
        selection_repository,
    )


def test_confirmation_saves_ids_in_requested_order() -> None:
    service, run_repository, selection_repository = _service()
    run_repository.get_by_id.return_value = _run(LiteratureRunStatus.COMPLETED)
    run_repository.get_run_papers.return_value = [
        LiteratureRunPaper(paper_id=42, position=0),
        LiteratureRunPaper(paper_id=51, position=1),
    ]
    saved = PaperSelection(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
        selected_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    selection_repository.create.return_value = saved

    result = asyncio.run(
        service.confirm_selection(
            7,
            PaperSelectionRequest(
                selected_paper_ids=[51, 42],
                code_requirements="Use PyTorch",
            ),
        )
    )

    assert result == saved
    selection = selection_repository.create.await_args.args[0]
    assert selection.selected_paper_ids == [51, 42]
    assert selection.code_requirements == "Use PyTorch"
    assert selection.selected_at is None
    run_repository.get_run_papers.assert_awaited_once_with(7)


def test_confirmation_rejects_paper_from_another_run() -> None:
    service, run_repository, selection_repository = _service()
    run_repository.get_by_id.return_value = _run(LiteratureRunStatus.COMPLETED)
    run_repository.get_run_papers.return_value = [
        LiteratureRunPaper(paper_id=42, position=0)
    ]

    with pytest.raises(InvalidPaperSelectionError) as exc_info:
        asyncio.run(
            service.confirm_selection(
                7, PaperSelectionRequest(selected_paper_ids=[42, 51, 61])
            )
        )

    assert exc_info.value.invalid_paper_ids == [51, 61]
    selection_repository.create.assert_not_awaited()


def test_confirmation_rejects_unknown_run_without_loading_papers() -> None:
    service, run_repository, selection_repository = _service()
    run_repository.get_by_id.return_value = None

    with pytest.raises(LiteratureRunNotFoundError, match="Run with id 99 not found"):
        asyncio.run(
            service.confirm_selection(
                99, PaperSelectionRequest(selected_paper_ids=[42])
            )
        )

    run_repository.get_run_papers.assert_not_awaited()
    selection_repository.get_by_run_id.assert_not_awaited()


def test_confirmation_rejects_unfinished_run_without_loading_papers() -> None:
    service, run_repository, selection_repository = _service()
    run_repository.get_by_id.return_value = _run(LiteratureRunStatus.RUNNING)

    with pytest.raises(LiteratureRunStateError, match="not in a valid state"):
        asyncio.run(
            service.confirm_selection(
                7, PaperSelectionRequest(selected_paper_ids=[42])
            )
        )

    run_repository.get_run_papers.assert_not_awaited()
    selection_repository.get_by_run_id.assert_not_awaited()


def test_confirmation_rejects_duplicate_submission() -> None:
    service, run_repository, selection_repository = _service()
    run_repository.get_by_id.return_value = _run(LiteratureRunStatus.COMPLETED)
    selection_repository.get_by_run_id.return_value = PaperSelection(
        run_id=7,
        selected_paper_ids=[42],
    )

    with pytest.raises(PaperSelectionAlreadyExistsError, match="already exists"):
        asyncio.run(
            service.confirm_selection(
                7, PaperSelectionRequest(selected_paper_ids=[42])
            )
        )

    run_repository.get_run_papers.assert_not_awaited()
    selection_repository.create.assert_not_awaited()
