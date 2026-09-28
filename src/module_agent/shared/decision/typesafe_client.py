from typesafe_sdk import AsyncTypeSafeClient

from module_agent.shared.config import app_settings


class TypeSafeClientManager:
    """管理外部客户端及其生命周期。"""
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
    ) -> None:
        """初始化当前对象。"""
        self.api_key = api_key.strip()
        self.model = model.strip()
        self.timeout_seconds = timeout_seconds
        self._client: AsyncTypeSafeClient | None = None

        if not self.model:
            raise ValueError("TypeSafe model cannot be empty")

        if timeout_seconds <= 0:
            raise ValueError(
                "TypeSafe timeout must be greater than zero"
            )

    def get_client(self) -> AsyncTypeSafeClient:
        """获取对应记录。"""
        if not self.api_key:
            raise RuntimeError(
                "TypeSafe API key is not configured"
            )

        if self._client is None:
            self._client = AsyncTypeSafeClient(
                api_key=self.api_key,
                model=self.model,
                timeout=self.timeout_seconds,
            )

        return self._client

    async def close(self) -> None:
        """关闭并释放外部资源。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


typesafe_client_manager = TypeSafeClientManager(
    api_key=app_settings.typesafe_api_key,
    model=app_settings.typesafe_model,
    timeout_seconds=app_settings.typesafe_timeout_seconds,
)
