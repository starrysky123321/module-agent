"""RabbitMQ consumer for a resource-specific Code Agent queue."""

import logging

from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from module_agent.code.adapters.messaging.topology import (
    declare_code_job_topology,
)
from module_agent.code.domain.jobs import (
    CodeJob,
    CodeJobHandler,
    ComputeTarget,
)
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


class RabbitMQCodeJobConsumer:
    """Consumes either CPU or GPU jobs with bounded concurrency."""

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
        """Consume jobs until the worker is stopped."""
        connection = await self.connection_manager.get_connection()
        async with connection.channel() as channel:
            await channel.set_qos(prefetch_count=self.prefetch_count)
            queue = await declare_code_job_topology(
                channel, target=self.compute_target
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
            self.logger.warning("Invalid code job message", exc_info=True)
            await message.reject(requeue=False)
            return
        if job.compute_target is not self.compute_target:
            self.logger.error("Code job was routed to the wrong worker pool")
            await message.reject(requeue=False)
            return
        message_id = getattr(message, "message_id", None)
        if isinstance(message_id, str) and message_id:
            job = job.model_copy(update={"message_id": message_id})
        try:
            await handler(job)
        except Exception:
            self.logger.exception("Code job execution failed")
            await message.reject(requeue=True)
            return
        await message.ack()
