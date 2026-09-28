import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from module_agent.literature.adapters.sources.http_client import (
    LiteratureHttpClientManager,
)


@pytest.mark.parametrize(
    ("timeout_seconds", "max_connections"),
    [(0, 10), (-1, 10), (30, 0), (30, -1)],
)
def test_source_client_rejects_invalid_limits(
    timeout_seconds: float,
    max_connections: int,
) -> None:
    with pytest.raises(ValueError):
        LiteratureHttpClientManager(
            timeout_seconds=timeout_seconds,
            max_connections=max_connections,
        )


def test_source_client_is_reused_and_closed() -> None:
    client = MagicMock(spec=httpx.AsyncClient)
    client.aclose = AsyncMock()
    manager = LiteratureHttpClientManager(
        timeout_seconds=20,
        max_connections=5,
    )

    with patch(
        "module_agent.literature.adapters.sources.http_client.httpx.AsyncClient",
        return_value=client,
    ) as client_class:
        assert manager.get_client() is client
        assert manager.get_client() is client
        asyncio.run(manager.close())

    client_class.assert_called_once()
    assert client_class.call_args.kwargs["timeout"] == 20
    limits = client_class.call_args.kwargs["limits"]
    assert isinstance(limits, httpx.Limits)
    client.aclose.assert_awaited_once_with()
    assert manager._client is None
