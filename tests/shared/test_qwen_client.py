import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from module_agent.shared.llm.qwen_client import QwenClientManager


@pytest.mark.parametrize(
    ("api_key", "base_url", "error_pattern"),
    [
        ("   ", "https://example.invalid/v1", "API key"),
        ("test-key", "   ", "base URL"),
    ],
)
def test_qwen_client_manager_rejects_missing_configuration(
    api_key: str,
    base_url: str,
    error_pattern: str,
) -> None:
    manager = QwenClientManager(api_key, base_url)

    with (
        patch(
            "module_agent.shared.llm.qwen_client.AsyncOpenAI"
        ) as client_class,
        pytest.raises(RuntimeError, match=error_pattern),
    ):
        manager.get_client()

    client_class.assert_not_called()


def test_qwen_client_manager_reuses_closes_and_recreates_client() -> None:
    first_client = MagicMock()
    first_client.close = AsyncMock()
    second_client = MagicMock()
    second_client.close = AsyncMock()
    manager = QwenClientManager(
        "  test-key  ",
        "  https://example.invalid/v1  ",
    )

    with patch(
        "module_agent.shared.llm.qwen_client.AsyncOpenAI",
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
        call(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
        call(
            api_key="test-key",
            base_url="https://example.invalid/v1",
        ),
    ]
    first_client.close.assert_awaited_once_with()
    second_client.close.assert_not_awaited()


def test_qwen_client_manager_close_is_noop_before_creation() -> None:
    manager = QwenClientManager("test-key", "https://example.invalid/v1")

    asyncio.run(manager.close())

    assert manager._client is None
