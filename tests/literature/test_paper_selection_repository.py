import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.shared.exceptions import PaperSelectionAlreadyExistsError
from module_agent.literature.domain.selection import PaperSelection
from module_agent.literature.adapters.database.models.selection import (
    PaperSelectionModel,
)
from module_agent.literature.adapters.database.repositories.selection import (
    SqlAlchemyPaperSelectionRepository,
)


def test_repository_returns_selection_by_run_id() -> None:
    selected_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    model = PaperSelectionModel(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
        selected_at=selected_at,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = model
    repository = SqlAlchemyPaperSelectionRepository(session)

    selection = asyncio.run(repository.get_by_run_id(7))

    assert selection == PaperSelection(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
        selected_at=selected_at,
    )
    session.get.assert_awaited_once_with(PaperSelectionModel, 7)


def test_repository_returns_none_for_unknown_run_id() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None
    repository = SqlAlchemyPaperSelectionRepository(session)

    assert asyncio.run(repository.get_by_run_id(99)) is None


def test_repository_creates_orm_model_without_commit() -> None:
    selected_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    session = AsyncMock(spec=AsyncSession)

    def assign_database_defaults(model: PaperSelectionModel) -> None:
        model.selected_at = selected_at

    session.refresh.side_effect = assign_database_defaults
    repository = SqlAlchemyPaperSelectionRepository(session)

    created = asyncio.run(
        repository.create(
            PaperSelection(
                run_id=7,
                selected_paper_ids=[51, 42],
                code_requirements="Use PyTorch",
            )
        )
    )

    model = session.add.call_args.args[0]
    assert isinstance(model, PaperSelectionModel)
    assert model.run_id == 7
    assert model.selected_paper_ids == [51, 42]
    assert created.selected_at == selected_at
    session.flush.assert_awaited_once_with()
    session.refresh.assert_awaited_once_with(model)
    session.commit.assert_not_awaited()


def test_repository_maps_insert_conflict_without_owning_rollback() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.flush.side_effect = IntegrityError(
        "INSERT INTO paper_selections",
        {},
        Exception("duplicate key"),
    )
    repository = SqlAlchemyPaperSelectionRepository(session)

    with pytest.raises(PaperSelectionAlreadyExistsError) as exc_info:
        asyncio.run(
            repository.create(
                PaperSelection(run_id=7, selected_paper_ids=[51, 42])
            )
        )

    assert exc_info.value.run_id == 7
    session.refresh.assert_not_awaited()
    session.rollback.assert_not_awaited()
    session.commit.assert_not_awaited()
