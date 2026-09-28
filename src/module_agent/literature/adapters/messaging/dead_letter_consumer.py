from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager
from module_agent.literature.domain.jobs import LiteratureJobHandler
from module_agent.literature.adapters.messaging.topology import declare_literature_dead_queue
from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError
from module_agent.literature.domain.jobs import LiteratureJob
import logging


class RabbitMQLiteratureDeadConsumer:
    """封装 RabbitMQLiteratureDeadConsumer 相关的数据和行为。"""
    def __init__(self,  connection_manager: RabbitMQConnectionManager,
                 dead_queue_name: str = "literature.jobs.dead.v1",
                 prefetch_count: int = 1) -> None:
        
        """初始化当前对象。"""
        if not dead_queue_name.strip():
            raise ValueError("dead_queue_name must be non-empty")

        self.dead_queue_name = dead_queue_name.strip()
        if prefetch_count <= 0:
            raise ValueError("prefetch_count must be greater than 0")
        self.connection_manager = connection_manager
        self.prefetch_count = prefetch_count
        self.logger = logging.getLogger(__name__)
    
    async def run(
        self,
        handler: LiteratureJobHandler,
    ) -> None:
        """执行当前任务。"""
        connection = await self.connection_manager.get_connection()
        
        async with connection.channel() as channel:
            await channel.set_qos(
                prefetch_count=self.prefetch_count,
            )
            
            queue = await declare_literature_dead_queue(
                channel,
                dead_queue_name=self.dead_queue_name,
            )
            
            async with queue.iterator() as messages:
                async for message in messages:
                    await self._process_message(message, handler)
            
    
    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        handler: LiteratureJobHandler,
    ) -> None:
        try:
            job = LiteratureJob.model_validate_json(message.body)
        except ValidationError:
            self.logger.warning("Invalid literature job message", exc_info=True)
            await message.reject(requeue=False)
            return
        
        try:
            await handler(job)
        except Exception:
            self.logger.exception("Literature job execution failed")
            await message.reject(requeue=True)
            return
        else:
            await message.ack()
