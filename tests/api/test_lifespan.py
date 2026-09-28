import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from module_agent.api.lifespan import lifespan


def _replace_resource_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    start = AsyncMock()
    close_checkpointer = AsyncMock()
    dispose_database = AsyncMock()
    close_redis = AsyncMock()
    close_rabbitmq = AsyncMock()
    close_github = AsyncMock()
    close_qwen = AsyncMock()
    monkeypatch.setattr(
        "module_agent.api.lifespan.postgres_checkpointer_manager",
        SimpleNamespace(start=start, close=close_checkpointer),
    )
    monkeypatch.setattr(
        "module_agent.api.lifespan.database_engine",
        SimpleNamespace(dispose=dispose_database),
    )
    monkeypatch.setattr(
        "module_agent.api.lifespan.redis_client",
        SimpleNamespace(aclose=close_redis),
    )
    monkeypatch.setattr(
        "module_agent.api.lifespan.rabbitmq_connection_manager",
        SimpleNamespace(close=close_rabbitmq),
    )
    monkeypatch.setattr(
        "module_agent.api.lifespan.github_client_manager",
        SimpleNamespace(close=close_github),
    )
    monkeypatch.setattr(
        "module_agent.api.lifespan.qwen_client_manager",
        SimpleNamespace(close=close_qwen),
    )
    return (
        start,
        close_checkpointer,
        dispose_database,
        close_redis,
        close_rabbitmq,
        close_github,
        close_qwen,
    )


def test_lifespan_starts_and_closes_application_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _replace_resource_methods(monkeypatch)

    async def run_lifespan() -> None:
        async with lifespan(FastAPI()):
            resources[0].assert_awaited_once_with()
            resources[1].assert_not_awaited()

    asyncio.run(run_lifespan())

    for resource in resources:
        resource.assert_awaited_once_with()


def test_lifespan_cleans_up_when_checkpointer_start_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resources = _replace_resource_methods(monkeypatch)
    resources[0].side_effect = RuntimeError("connection failed")

    async def run_lifespan() -> None:
        async with lifespan(FastAPI()):
            raise AssertionError("lifespan should not yield")

    with pytest.raises(RuntimeError, match="connection failed"):
        asyncio.run(run_lifespan())

    for resource in resources:
        resource.assert_awaited_once_with()
