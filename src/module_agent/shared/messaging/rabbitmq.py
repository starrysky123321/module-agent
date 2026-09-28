import asyncio

from aio_pika import connect_robust
from aio_pika.abc import AbstractRobustConnection

from module_agent.shared.config import app_settings


class RabbitMQConnectionManager:
    """管理外部客户端及其生命周期。"""
    def __init__(self, rabbitmq_url: str) -> None:
        """初始化当前对象。"""
        normalized_url = rabbitmq_url.strip()
        if not normalized_url:
            raise ValueError("RabbitMQ URL cannot be empty")

        self.rabbitmq_url = normalized_url
        self.connection: AbstractRobustConnection | None = None
        self._lock = asyncio.Lock()

    async def get_connection(self) -> AbstractRobustConnection:
        """获取对应记录。"""
        if self.connection is None or self.connection.is_closed:
            async with self._lock:
                if self.connection is None or self.connection.is_closed:
                    self.connection = await connect_robust(self.rabbitmq_url)

        assert self.connection is not None
        return self.connection

    async def close(self) -> None:
        """关闭并释放外部资源。"""
        if self.connection is not None and not self.connection.is_closed:
            await self.connection.close()

        self.connection = None


rabbitmq_connection_manager = RabbitMQConnectionManager(
    app_settings.rabbitmq_url,
)
