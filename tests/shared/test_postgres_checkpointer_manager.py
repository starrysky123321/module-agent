import asyncio
from typing import Any

import pytest

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
