import asyncio
from unittest.mock import AsyncMock

import pytest

from module_agent.cli.setup_langgraph_checkpointer import setup_checkpointer


class FakeCheckpointerContext:
    def __init__(self) -> None:
        self.checkpointer = type(
            "FakeCheckpointer",
            (),
            {"setup": AsyncMock()},
        )()
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self.checkpointer

    async def __aexit__(self, *args: object) -> None:
        self.exit_count += 1


def test_setup_checkpointer_creates_schema_and_closes_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = FakeCheckpointerContext()
    captured_urls: list[str] = []

    def from_conn_string(database_url: str) -> FakeCheckpointerContext:
        captured_urls.append(database_url)
        return context

    monkeypatch.setattr(
        "module_agent.cli.setup_langgraph_checkpointer."
        "app_settings.langgraph_database_url",
        "  postgresql://user:password@localhost/database  ",
    )
    monkeypatch.setattr(
        "module_agent.cli.setup_langgraph_checkpointer."
        "AsyncPostgresSaver.from_conn_string",
        from_conn_string,
    )

    asyncio.run(setup_checkpointer())

    assert captured_urls == ["postgresql://user:password@localhost/database"]
    context.checkpointer.setup.assert_awaited_once_with()
    assert context.enter_count == 1
    assert context.exit_count == 1


def test_setup_checkpointer_rejects_empty_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "module_agent.cli.setup_langgraph_checkpointer."
        "app_settings.langgraph_database_url",
        "   ",
    )

    with pytest.raises(RuntimeError, match="empty"):
        asyncio.run(setup_checkpointer())
