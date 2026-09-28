"""RabbitMQ consumer for exhausted Code Agent jobs."""

import logging

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from module_agent.code.adapters.messaging.topology import (
    declare_code_dead_queue,
)
from module_agent.code.domain.jobs import (
    CodeJob,
    CodeJobHandler,
    ComputeTarget,
)
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


class RabbitMQCodeDeadConsumer:
    """Consume jobs moved to a compute pool's dead-letter queue."""

    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        *,
        compute_target: ComputeTarget,
        prefetch_count: int = 1,
    ) -> None:
        if prefetch_count < 1:
            raise ValueError("prefetch_count must be positive")
        self.connection_manager = connection_manager
        self.compute_target = compute_target
        self.prefetch_count = prefetch_count
        self.logger = logging.getLogger(__name__)

    async def run(self, handler: CodeJobHandler) -> None:
        """Consume dead-letter jobs until the worker is stopped."""
        connection = await self.connection_manager.get_connection()
        async with connection.channel() as channel:
            await channel.set_qos(prefetch_count=self.prefetch_count)
            queue = await declare_code_dead_queue(
                channel,
                target=self.compute_target,
            )
            async with queue.iterator() as messages:
                async for message in messages:
                    await self._process_message(message, handler)

    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        handler: CodeJobHandler,
    ) -> None:
        try:
            job = CodeJob.model_validate_json(message.body)
        except ValidationError:
            self.logger.warning("Invalid dead code job message", exc_info=True)
            await message.reject(requeue=False)
            return
        if job.compute_target is not self.compute_target:
            self.logger.error("Dead code job was routed to the wrong pool")
            await message.reject(requeue=False)
            return
        try:
            await handler(job)
        except Exception:
            self.logger.exception("Dead code job recovery failed")
            await message.reject(requeue=True)
            return
        await message.ack()
