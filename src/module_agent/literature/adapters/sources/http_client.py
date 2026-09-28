"""Shared HTTP client lifecycle for literature source adapters."""

import httpx

from module_agent.shared.config import app_settings


class LiteratureHttpClientManager:
    """Reuse bounded HTTP connections across source searches."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_connections: int,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_connections <= 0:
            raise ValueError("max_connections must be positive")
        self.timeout_seconds = timeout_seconds
        self.max_connections = max_connections
        self._client: httpx.AsyncClient | None = None

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                limits=httpx.Limits(
                    max_connections=self.max_connections,
                    max_keepalive_connections=self.max_connections,
                ),
                headers={"User-Agent": "module-agent/1.0"},
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


literature_http_client_manager = LiteratureHttpClientManager(
    timeout_seconds=app_settings.literature_http_timeout_seconds,
    max_connections=app_settings.literature_http_max_connections,
)
