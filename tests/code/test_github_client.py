import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from module_agent.code.adapters.github_client import GitHubClientManager


@pytest.mark.parametrize(
    ("base_url", "timeout_seconds"),
    [
        ("", 30.0),
        ("   ", 30.0),
        ("https://api.github.test", 0),
        ("https://api.github.test", -1),
    ],
)
def test_manager_rejects_invalid_configuration(
    base_url: str,
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError):
        GitHubClientManager(base_url, timeout_seconds)


def test_manager_reuses_closes_and_recreates_client() -> None:
    first_client = MagicMock()
    first_client.aclose = AsyncMock()
    second_client = MagicMock()
    second_client.aclose = AsyncMock()
    manager = GitHubClientManager(
        "  https://api.github.test  ",
        45.0,
    )

    with patch(
        "module_agent.code.adapters.github_client.httpx.AsyncClient",
        side_effect=[first_client, second_client],
    ) as client_class:
        first_result = manager.get_client()
        reused_result = manager.get_client()
        asyncio.run(manager.close())
        recreated_result = manager.get_client()

    assert first_result is first_client
    assert reused_result is first_client
    assert recreated_result is second_client
    assert client_class.call_args_list == [
        call(base_url="https://api.github.test", timeout=45.0),
        call(base_url="https://api.github.test", timeout=45.0),
    ]
    first_client.aclose.assert_awaited_once_with()
    second_client.aclose.assert_not_awaited()


def test_manager_close_is_noop_before_creation() -> None:
    manager = GitHubClientManager("https://api.github.test", 30.0)

    asyncio.run(manager.close())

    assert manager._client is None
