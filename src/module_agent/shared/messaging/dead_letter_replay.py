"""Bounded RabbitMQ dead-letter replay for workflow completion events."""

from collections.abc import Callable
import logging
from typing import Any
from uuid import uuid4

from aio_pika import DeliveryMode, Message
from aio_pika.abc import (
    AbstractChannel,
    AbstractExchange,
    AbstractIncomingMessage,
    AbstractQueue,
)

from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


REPLAY_COUNT_HEADER = "x-module-agent-replay-count"
REPLAY_REASON_HEADER = "x-module-agent-park-reason"
PayloadValidator = Callable[[bytes], object]


class RabbitMQDeadLetterReplayer:
    """Delay and replay transient dead letters, parking exhausted messages."""

    def __init__(
        self,
        connection_manager: RabbitMQConnectionManager,
        *,
        live_queue_name: str,
        dead_queue_name: str,
        retry_queue_name: str,
        parked_queue_name: str,
        payload_validator: PayloadValidator,
        max_replays: int = 3,
        retry_delay_ms: int = 30_000,
    ) -> None:
        names = {
            live_queue_name.strip(),
            dead_queue_name.strip(),
            retry_queue_name.strip(),
            parked_queue_name.strip(),
        }
        if "" in names:
            raise ValueError("queue names must be non-empty")
        if len(names) != 4:
            raise ValueError("completion recovery queue names must be unique")
        if not 1 <= max_replays <= 20:
            raise ValueError("max_replays must be between 1 and 20")
        if not 1_000 <= retry_delay_ms <= 3_600_000:
            raise ValueError(
                "retry_delay_ms must be between 1000 and 3600000"
            )
        self.connection_manager = connection_manager
        self.live_queue_name = live_queue_name.strip()
        self.dead_queue_name = dead_queue_name.strip()
        self.retry_queue_name = retry_queue_name.strip()
        self.parked_queue_name = parked_queue_name.strip()
        self.payload_validator = payload_validator
        self.max_replays = max_replays
        self.retry_delay_ms = retry_delay_ms
        self.logger = logging.getLogger(__name__)

    async def run(self) -> None:
        """Consume dead letters until the process is stopped."""
        connection = await self.connection_manager.get_connection()
        async with connection.channel(publisher_confirms=True) as channel:
            await channel.set_qos(prefetch_count=1)
            dead_queue = await self._declare_topology(channel)
            async with dead_queue.iterator() as messages:
                async for message in messages:
                    await self._process_message(
                        message,
                        channel.default_exchange,
                    )

    async def _declare_topology(
        self,
        channel: AbstractChannel,
    ) -> AbstractQueue:
        await channel.declare_queue(
            self.live_queue_name,
            durable=True,
            passive=True,
        )
        dead_queue = await channel.declare_queue(
            self.dead_queue_name,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )
        await channel.declare_queue(
            self.retry_queue_name,
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": self.retry_delay_ms,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": self.live_queue_name,
            },
        )
        await channel.declare_queue(
            self.parked_queue_name,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )
        return dead_queue

    async def _process_message(
        self,
        message: AbstractIncomingMessage,
        exchange: AbstractExchange,
    ) -> None:
        headers: dict[str, Any] = dict(message.headers or {})
        try:
            self.payload_validator(message.body)
            replay_count = _read_replay_count(headers)
        except (TypeError, ValueError):
            await self._publish_then_ack(
                message,
                exchange,
                routing_key=self.parked_queue_name,
                replay_count=0,
                park_reason="invalid-payload-or-replay-header",
            )
            return

        if replay_count >= self.max_replays:
            await self._publish_then_ack(
                message,
                exchange,
                routing_key=self.parked_queue_name,
                replay_count=replay_count,
                park_reason="replay-limit-exceeded",
            )
            return

        await self._publish_then_ack(
            message,
            exchange,
            routing_key=self.retry_queue_name,
            replay_count=replay_count + 1,
        )

    async def _publish_then_ack(
        self,
        source: AbstractIncomingMessage,
        exchange: AbstractExchange,
        *,
        routing_key: str,
        replay_count: int,
        park_reason: str | None = None,
    ) -> None:
        headers: dict[str, Any] = {
            REPLAY_COUNT_HEADER: replay_count,
        }
        if park_reason is not None:
            headers[REPLAY_REASON_HEADER] = park_reason
        try:
            await exchange.publish(
                Message(
                    body=source.body,
                    content_type=source.content_type or "application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    headers=headers,
                    message_id=source.message_id or uuid4().hex,
                    correlation_id=source.correlation_id,
                ),
                routing_key=routing_key,
                mandatory=True,
            )
        except Exception:
            self.logger.exception(
                "Failed to republish completion dead letter",
                extra={"target_queue": routing_key},
            )
            await source.reject(requeue=True)
            return
        await source.ack()


def _read_replay_count(headers: dict[str, Any]) -> int:
    value = headers.get(REPLAY_COUNT_HEADER, 0)
    if isinstance(value, bool):
        raise ValueError("invalid replay count")
    try:
        count = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid replay count") from exc
    if count < 0:
        raise ValueError("invalid replay count")
    return count
