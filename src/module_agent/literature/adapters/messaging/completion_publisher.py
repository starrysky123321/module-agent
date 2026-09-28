from uuid import uuid4

from aio_pika import DeliveryMode, Message

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
)
from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.topology import (
    declare_literature_topology,
)


class RabbitMQLiteratureCompletionPublisher:
    """封装 RabbitMQLiteratureCompletionPublisher 相关的数据和行为。"""
    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        queue_name: str = "literature.completed.v1",
        dead_queue_name: str = "literature.completed.dead.v1",
    ) -> None:
        """初始化当前对象。"""
        if not queue_name.strip():
            raise ValueError("queue_name must be non-empty")
        if not dead_queue_name.strip():
            raise ValueError("dead_queue_name must be non-empty")

        self.connection_manager = connection_manager
        self.queue_name = queue_name.strip()
        self.dead_queue_name = dead_queue_name.strip()

    async def publish(self, run_id: int) -> str:
        """发布对应消息。"""
        if type(run_id) is not int or run_id <= 0:
            raise ValueError("run_id must be a positive integer")

        event = LiteratureCompletedEvent(run_id=run_id)
        message_id = uuid4().hex
        connection = await self.connection_manager.get_connection()

        async with connection.channel(
            publisher_confirms=True,
        ) as channel:
            queue = await declare_literature_topology(
                channel,
                queue_name=self.queue_name,
                dead_queue_name=self.dead_queue_name,
            )
            message = Message(
                body=event.model_dump_json().encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=message_id,
            )
            await channel.default_exchange.publish(
                message,
                routing_key=queue.name,
                mandatory=True,
            )

        return message_id
