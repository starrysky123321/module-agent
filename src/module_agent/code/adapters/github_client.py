import httpx
from module_agent.shared.config import app_settings

class GitHubClientManager:
    """管理外部客户端及其生命周期。"""
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
    ):
        """初始化当前对象。"""
        self.base_url = base_url.strip()
        if not self.base_url:
            raise ValueError("base_url is required")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        
        self.timeout_seconds = timeout_seconds
        self._client: httpx.AsyncClient | None = None
        
    def get_client(self) -> httpx.AsyncClient:
        """获取对应记录。"""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self._client

    async def close(self) -> None:
        """关闭并释放外部资源。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            

github_client_manager = GitHubClientManager(
    base_url=app_settings.github_api_url,
    timeout_seconds=app_settings.github_timeout_seconds,
)
