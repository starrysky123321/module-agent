import json
from uuid import UUID, uuid4
from aio_pika import DeliveryMode, Message

from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.topology import (
    declare_literature_topology,
)


class RabbitMQLiteratureJobQueue:
    """封装 RabbitMQLiteratureJobQueue 相关的数据和行为。"""
    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        queue_name: str = "literature.jobs.v2",
    ) -> None:
        """初始化当前对象。"""
        normalized_queue_name = queue_name.strip()
        
        if not normalized_queue_name:
            raise ValueError("queue_name must be non-empty")
        
        self.connection_manager = connection_manager
        self.queue_name = normalized_queue_name

    async def enqueue(
        self,
        run_id: int,
        resume_workflow: bool = False,
        trace_id: UUID | None = None,
    ) -> str:
        """把任务消息写入主队列。"""
        if run_id <= 0:
            raise ValueError("Run id must be positive")

        # 1. 生成我们自己的消息 ID
        message_id = uuid4().hex

        # 2. 从步骤一的管理器获取 RabbitMQ 连接
        connection = await self.connection_manager.get_connection()

        # 3. 创建 Channel
        async with connection.channel(publisher_confirms=True) as channel:
            # 4. 声明任务队列
            queue = await declare_literature_topology(
                channel,
                queue_name=self.queue_name,
            )

            # 5. 创建消息
            payload = {
                "run_id": run_id,
                "resume_workflow": resume_workflow,
            }
            if trace_id is not None:
                payload["trace_id"] = str(trace_id)
            message = Message(
                body=json.dumps(payload).encode("utf-8"),
                content_type="application/json",
                delivery_mode=DeliveryMode.PERSISTENT,
                message_id=message_id,
            )

            # 6. 发送到队列
            await channel.default_exchange.publish(
                message,
                routing_key=queue.name,
                mandatory=True,
            )

        # 7. 返回消息 ID
        return message_id




        
        
