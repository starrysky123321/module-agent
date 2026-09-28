"""RabbitMQ adapters for CodeRun completion events."""

import logging
from uuid import uuid4

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractIncomingMessage
from pydantic import ValidationError

from module_agent.code.adapters.messaging.topology import (
    declare_code_completion_topology,
)
from module_agent.code.domain.events import (
    CodeCompletedEvent,
    CodeCompletionHandler,
)
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


class RabbitMQCodeCompletionPublisher:
    """Publishes persisted CodeRun identifiers, not large artifacts."""

    def __init__(self, connection_manager: RabbitMQConnectionManager) -> None:
        self.connection_manager = connection_manager

    async def publish(self, event: CodeCompletedEvent) -> str:
        message_id = uuid4().hex
        connection = await self.connection_manager.get_connection()
        async with connection.channel(publisher_confirms=True) as channel:
            queue = await declare_code_completion_topology(channel)
            await channel.default_exchange.publish(
                Message(
                    body=event.model_dump_json().encode("utf-8"),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    message_id=message_id,
                ),
                routing_key=queue.name,
                mandatory=True,
            )
        return message_id


class RabbitMQCodeCompletionConsumer:
    """Consumes workflow resume signals from Code Workers."""

    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        *,
        prefetch_count: int = 1,
    ) -> None:
        if prefetch_count < 1:
            raise ValueError("prefetch_count must be positive")
        self.connection_manager = connection_manager
        self.prefetch_count = prefetch_count
        self.logger = logging.getLogger(__name__)

    async def run(self, handler: CodeCompletionHandler) -> None:
        connection = await self.connection_manager.get_connection()
        async with connection.channel() as channel:
            await channel.set_qos(prefetch_count=self.prefetch_count)
            queue = await declare_code_completion_topology(channel)
            async with queue.iterator() as messages:
                async for message in messages:
                    await self._process_message(message, handler)

    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        handler: CodeCompletionHandler,
    ) -> None:
        try:
            event = CodeCompletedEvent.model_validate_json(message.body)
        except ValidationError:
            self.logger.warning("Invalid code completion event", exc_info=True)
            await message.reject(requeue=False)
            return
        try:
            await handler(event)
        except Exception:
            self.logger.exception("Code completion handling failed")
            await message.reject(requeue=True)
            return
        await message.ack()
