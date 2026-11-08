"""Every workflow DB operation releases its transaction before graph I/O."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from module_agent.literature.adapters.database.repositories import (
    transactional as adapters,
)


@pytest.mark.parametrize(
    "method,args,write,wrapper,implementation",
    [
        (
            "get_by_id",
            (1,),
            False,
            "TransactionalLiteratureRunRepository",
            "SqlAlchemyLiteratureRunRepository",
        ),
        (
            "get_run_papers",
            (1,),
            False,
            "TransactionalLiteratureRunRepository",
            "SqlAlchemyLiteratureRunRepository",
        ),
        (
            "save",
            (object(),),
            True,
            "TransactionalLiteratureRunRepository",
            "SqlAlchemyLiteratureRunRepository",
        ),
        (
            "replace_papers",
            (1, []),
            True,
            "TransactionalLiteratureRunRepository",
            "SqlAlchemyLiteratureRunRepository",
        ),
        (
            "get_by_run_id",
            (1,),
            False,
            "TransactionalPaperSelectionRepository",
            "SqlAlchemyPaperSelectionRepository",
        ),
        (
            "create",
            (object(),),
            True,
            "TransactionalPaperSelectionRepository",
            "SqlAlchemyPaperSelectionRepository",
        ),
        (
            "get_by_ids",
            ([1],),
            False,
            "TransactionalPaperRepository",
            "SqlAlchemyPaperRepository",
        ),
        (
            "get_by_doi",
            ("10.test/fixture",),
            False,
            "TransactionalPaperRepository",
            "SqlAlchemyPaperRepository",
        ),
        (
            "get_by_source",
            ("fixture", "1"),
            False,
            "TransactionalPaperRepository",
            "SqlAlchemyPaperRepository",
        ),
        (
            "save",
            (object(),),
            True,
            "TransactionalPaperRepository",
            "SqlAlchemyPaperRepository",
        ),
    ],
)
@pytest.mark.parametrize("fail", [False, True])
def test_repository_closes_session_and_commits_or_rolls_back(
    monkeypatch, method, args, write, wrapper, implementation, fail
):
    events = []

    @asynccontextmanager
    async def transaction():
        events.append("begin")
        try:
            yield
        except ValueError:
            events.append("rollback")
            raise
        else:
            events.append("commit")

    session = MagicMock()
    session.begin = transaction

    @asynccontextmanager
    async def factory():
        events.append("open")
        try:
            yield session
        finally:
            events.append("close")

    async def operation(*_):
        events.append("operation")
        if fail:
            raise ValueError("db failure")
        return "detached domain value"

    repository = MagicMock()
    mocked = AsyncMock(side_effect=operation)
    setattr(repository, method, mocked)
    constructor = MagicMock(return_value=repository)
    monkeypatch.setattr(adapters, implementation, constructor)

    async def exercise():
        await getattr(getattr(adapters, wrapper)(factory), method)(*args)

    if fail:
        with pytest.raises(ValueError, match="db failure"):
            asyncio.run(exercise())
    else:
        asyncio.run(exercise())
    mocked.assert_awaited_once_with(*args)
    constructor.assert_called_once_with(session)
    assert events == (
        ["open", "begin", "operation", "rollback" if fail else "commit", "close"]
        if write
        else ["open", "operation", "close"]
    )
