import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from module_agent.shared.decision.typesafe_client import (
    TypeSafeClientManager,
)


def test_typesafe_client_manager_requires_configuration() -> None:
    with pytest.raises(ValueError, match="model cannot be empty"):
        TypeSafeClientManager(
            api_key="key",
            model="   ",
            timeout_seconds=3,
        )

    with pytest.raises(ValueError, match="greater than zero"):
        TypeSafeClientManager(
            api_key="key",
            model="jev-latest",
            timeout_seconds=0,
        )

    manager = TypeSafeClientManager(
        api_key="   ",
        model="jev-latest",
        timeout_seconds=3,
    )
    with pytest.raises(RuntimeError, match="API key is not configured"):
        manager.get_client()


def test_typesafe_client_manager_reuses_and_closes_client() -> None:
    client = MagicMock()
    client.aclose = AsyncMock()

    with patch(
        "module_agent.shared.decision.typesafe_client.AsyncTypeSafeClient",
        return_value=client,
    ) as client_factory:
        manager = TypeSafeClientManager(
            api_key="  secret-key  ",
            model="  jev-latest  ",
            timeout_seconds=4.5,
        )

        first = manager.get_client()
        second = manager.get_client()
        asyncio.run(manager.close())

    assert first is client
    assert second is client
    client_factory.assert_called_once_with(
        api_key="secret-key",
        model="jev-latest",
        timeout=4.5,
    )
    client.aclose.assert_awaited_once_with()
    assert manager._client is None


def test_typesafe_client_manager_close_is_idempotent() -> None:
    manager = TypeSafeClientManager(
        api_key="secret-key",
        model="jev-latest",
        timeout_seconds=3,
    )

    asyncio.run(manager.close())
