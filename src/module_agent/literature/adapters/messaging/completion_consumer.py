import logging

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
    LiteratureCompletionHandler,
)
from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.topology import (
    declare_literature_topology,
)


class RabbitMQLiteratureCompletionConsumer:
    """封装 RabbitMQLiteratureCompletionConsumer 相关的数据和行为。"""
    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        queue_name: str = "literature.completed.v1",
        dead_queue_name: str = "literature.completed.dead.v1",
        prefetch_count: int = 1,
    ) -> None:
        """初始化当前对象。"""
        if not queue_name.strip():
            raise ValueError("queue_name must be non-empty")
        if not dead_queue_name.strip():
            raise ValueError("dead_queue_name must be non-empty")
        if prefetch_count <= 0:
            raise ValueError("prefetch_count must be positive")

        self.connection_manager = connection_manager
        self.queue_name = queue_name.strip()
        self.dead_queue_name = dead_queue_name.strip()
        self.prefetch_count = prefetch_count
        self.logger = logging.getLogger(__name__)

    async def run(
        self,
        handler: LiteratureCompletionHandler,
    ) -> None:
        """执行当前任务。"""
        connection = await self.connection_manager.get_connection()

        async with connection.channel() as channel:
            await channel.set_qos(prefetch_count=self.prefetch_count)
            queue = await declare_literature_topology(
                channel,
                queue_name=self.queue_name,
                dead_queue_name=self.dead_queue_name,
            )

            async with queue.iterator() as messages:
                async for message in messages:
                    await self._process_message(message, handler)

    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        handler: LiteratureCompletionHandler,
    ) -> None:
        try:
            event = LiteratureCompletedEvent.model_validate_json(message.body)
        except ValidationError:
            self.logger.warning(
                "Invalid literature completion event",
                exc_info=True,
            )
            await message.reject(requeue=False)
            return

        try:
            await handler(event)
        except Exception:
            self.logger.exception(
                "Literature completion event handling failed"
            )
            await message.reject(requeue=True)
            return

        await message.ack()
