import asyncio
from typing import Any

import pytest
from psycopg import OperationalError

from module_agent.shared.checkpoint.postgres import (
    PostgresCheckpointerManager,
)


class FakeSaverContext:
    def __init__(self) -> None:
        self.saver = object()
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> Any:
        self.enter_count += 1
        return self.saver

    async def __aexit__(self, *args: object) -> None:
        self.exit_count += 1


def test_manager_starts_once_reuses_saver_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeSaverContext()
    captured_urls: list[str] = []

    def from_conn_string(database_url: str) -> FakeSaverContext:
        captured_urls.append(database_url)
        return context

    monkeypatch.setattr(
        "module_agent.shared.checkpoint.postgres."
        "AsyncPostgresSaver.from_conn_string",
        from_conn_string,
    )
    manager = PostgresCheckpointerManager(
        "  postgresql://user:password@localhost/database  "
    )

    async def exercise_manager() -> None:
        first, second = await asyncio.gather(
            manager.start(),
            manager.start(),
        )

        assert first is context.saver
        assert second is context.saver
        assert manager.get_checkpointer() is context.saver
        await manager.close()
        await manager.close()

    asyncio.run(exercise_manager())

    assert captured_urls == ["postgresql://user:password@localhost/database"]
    assert context.enter_count == 1
    assert context.exit_count == 1
    with pytest.raises(RuntimeError, match="started before using"):
        manager.get_checkpointer()


def test_manager_rejects_empty_database_url() -> None:
    manager = PostgresCheckpointerManager("   ")

    with pytest.raises(RuntimeError, match="database URL"):
        asyncio.run(manager.start())

    asyncio.run(manager.close())


def test_manager_rebuilds_pool_and_retries_operational_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contexts = [FakeSaverContext(), FakeSaverContext()]

    def from_conn_string(_: str) -> FakeSaverContext:
        return contexts.pop(0)

    monkeypatch.setattr(
        "module_agent.shared.checkpoint.postgres."
        "AsyncPostgresSaver.from_conn_string",
        from_conn_string,
    )
    manager = PostgresCheckpointerManager("postgresql://database")
    seen_savers: list[object] = []

    async def exercise_manager() -> str:
        attempts = 0

        async def operation(saver: Any) -> str:
            nonlocal attempts
            attempts += 1
            seen_savers.append(saver)
            if attempts == 1:
                raise OperationalError("connection closed")
            return "recovered"

        result = await manager.run_with_recovery(operation)
        await manager.close()
        return result

    assert asyncio.run(exercise_manager()) == "recovered"
    assert len(seen_savers) == 2
    assert seen_savers[0] is not seen_savers[1]


def test_manager_does_not_retry_application_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeSaverContext()
    monkeypatch.setattr(
        "module_agent.shared.checkpoint.postgres."
        "AsyncPostgresSaver.from_conn_string",
        lambda _: context,
    )
    manager = PostgresCheckpointerManager("postgresql://database")
    calls = 0

    async def exercise_manager() -> None:
        nonlocal calls

        async def operation(_: Any) -> None:
            nonlocal calls
            calls += 1
            raise ValueError("invalid workflow state")

        with pytest.raises(ValueError, match="invalid workflow state"):
            await manager.run_with_recovery(operation)
        await manager.close()

    asyncio.run(exercise_manager())
    assert calls == 1
