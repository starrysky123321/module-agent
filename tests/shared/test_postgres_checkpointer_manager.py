import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from psycopg import OperationalError
from psycopg.rows import dict_row

from module_agent.shared.checkpoint import postgres as checkpoint_module
from module_agent.shared.checkpoint.postgres import PostgresCheckpointerManager


@pytest.fixture
def pools(monkeypatch):
    created = []

    class FakePool:
        check_connection = staticmethod(AsyncMock())

        def __class_getitem__(cls, _):
            return cls

        def __init__(self, url, **kwargs):
            self.url, self.kwargs = url, kwargs
            self.closed = False
            self.wait = AsyncMock()
            self.connection = MagicMock()
            self.connection.return_value.__aenter__ = AsyncMock()
            self.connection.return_value.__aexit__ = AsyncMock(return_value=False)
            self.connection.return_value.__aenter__.return_value.execute = AsyncMock()
            created.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            self.closed = True

    monkeypatch.setattr(checkpoint_module, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(
        checkpoint_module,
        "AsyncPostgresSaver",
        MagicMock(side_effect=lambda pool: MagicMock(conn=pool)),
    )
    return created


def test_manager_starts_once_uses_checked_pool_and_closes(pools):
    manager = PostgresCheckpointerManager("  postgresql://database  ")

    async def exercise():
        first, second = await asyncio.gather(manager.start(), manager.start())
        assert first is second is manager.get_checkpointer()
        assert first.conn is pools[0]
        await manager.close()
        await manager.close()

    asyncio.run(exercise())
    assert len(pools) == 1
    pool = pools[0]
    assert pool.url == "postgresql://database"
    assert pool.closed
    assert pool.kwargs["min_size"] == 1 and pool.kwargs["max_size"] == 5
    assert pool.kwargs["timeout"] == 3
    assert pool.kwargs["check"] is pool.check_connection
    assert pool.kwargs["kwargs"] == {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
    }
    pool.wait.assert_awaited_once_with(timeout=5)
    with pytest.raises(RuntimeError, match="started before using"):
        manager.get_checkpointer()


def test_manager_rejects_empty_database_url():
    manager = PostgresCheckpointerManager("   ")
    with pytest.raises(RuntimeError, match="database URL"):
        asyncio.run(manager.start())
    asyncio.run(manager.close())


def test_manager_rebuilds_pool_and_retries_operational_failure(pools):
    manager = PostgresCheckpointerManager("postgresql://database")
    seen = []

    async def exercise():
        async def operation(saver):
            seen.append(saver)
            if len(seen) == 1:
                raise OperationalError("connection closed")
            return "recovered"

        result = await manager.run_with_recovery(operation)
        await manager.close()
        return result

    assert asyncio.run(exercise()) == "recovered"
    assert len(pools) == 2 and all(pool.closed for pool in pools)
    assert seen[0] is not seen[1]


def test_manager_does_not_retry_application_failure(pools):
    manager = PostgresCheckpointerManager("postgresql://database")
    operation = AsyncMock(side_effect=ValueError("invalid workflow state"))

    async def exercise():
        with pytest.raises(ValueError, match="invalid workflow state"):
            await manager.run_with_recovery(operation)
        await manager.close()

    asyncio.run(exercise())
    assert len(pools) == 1
    operation.assert_awaited_once()


def test_health_probes_active_pool_and_checkpoint_schema_without_writes(pools):
    manager = PostgresCheckpointerManager("postgresql://database")

    async def exercise():
        await manager.start()
        await manager.check_health()
        connection = pools[0].connection.return_value.__aenter__.return_value
        connection.execute.assert_awaited_once_with("SELECT 1 FROM checkpoints LIMIT 0")
        await manager.close()

    asyncio.run(exercise())


def test_health_rejects_unstarted_manager_without_creating_pool(pools):
    with pytest.raises(RuntimeError, match="not started"):
        asyncio.run(PostgresCheckpointerManager("postgresql://database").check_health())
    assert not pools


def test_health_propagates_checkpoint_failure(pools):
    manager = PostgresCheckpointerManager("postgresql://database")

    async def exercise():
        await manager.start()
        pools[
            0
        ].connection.return_value.__aenter__.return_value.execute.side_effect = (
            OperationalError("offline")
        )
        with pytest.raises(OperationalError):
            await manager.check_health()
        await manager.close()

    asyncio.run(exercise())


def test_manager_releases_pool_when_start_is_cancelled(pools, monkeypatch):
    manager = PostgresCheckpointerManager("postgresql://database")
    original_enter = checkpoint_module.AsyncConnectionPool.__aenter__

    async def enter(pool):
        await original_enter(pool)
        pool.wait.side_effect = asyncio.CancelledError()
        return pool

    monkeypatch.setattr(checkpoint_module.AsyncConnectionPool, "__aenter__", enter)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(manager.start())
    assert len(pools) == 1 and pools[0].closed
