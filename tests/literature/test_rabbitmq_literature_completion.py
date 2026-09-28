import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from aio_pika.abc import AbstractIncomingMessage

from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
)
from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.completion_publisher import (
    RabbitMQLiteratureCompletionPublisher,
)
from module_agent.literature.adapters.messaging.completion_consumer import (
    RabbitMQLiteratureCompletionConsumer,
)


def _incoming_message(body: bytes) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    return message


def test_completion_publisher_publishes_persistent_event() -> None:
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.declare_queue = AsyncMock(
        side_effect=[
            SimpleNamespace(name="literature.completed.dead.v1"),
            SimpleNamespace(name="literature.completed.v1"),
        ]
    )
    channel.default_exchange = exchange
    channel_context = MagicMock()
    channel_context.__aenter__ = AsyncMock(return_value=channel)
    channel_context.__aexit__ = AsyncMock(return_value=None)
    connection = MagicMock()
    connection.channel.return_value = channel_context
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    manager.get_connection.return_value = connection
    publisher = RabbitMQLiteratureCompletionPublisher(manager)

    message_id = asyncio.run(publisher.publish(42))

    assert message_id
    assert channel.declare_queue.await_args_list == [
        call(
            "literature.completed.dead.v1",
            durable=True,
            arguments={"x-queue-type": "quorum"},
        ),
        call(
            "literature.completed.v1",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-delivery-limit": 3,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": (
                    "literature.completed.dead.v1"
                ),
                "x-delayed-retry-type": "failed",
                "x-delayed-retry-min": 1000,
                "x-delayed-retry-max": 30000,
            },
        ),
    ]
    message = exchange.publish.await_args.args[0]
    assert json.loads(message.body.decode("utf-8")) == {"run_id": 42}
    assert message.message_id == message_id
    exchange.publish.assert_awaited_once_with(
        message,
        routing_key="literature.completed.v1",
        mandatory=True,
    )


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_completion_publisher_rejects_invalid_run_id(run_id: int) -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    publisher = RabbitMQLiteratureCompletionPublisher(manager)

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(publisher.publish(run_id))

    manager.get_connection.assert_not_awaited()


def test_completion_consumer_acknowledges_successful_event() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureCompletionConsumer(manager)
    message = _incoming_message(b'{"run_id": 8}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_awaited_once_with(LiteratureCompletedEvent(run_id=8))
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


def test_completion_consumer_rejects_invalid_event() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureCompletionConsumer(manager)
    message = _incoming_message(b'{"run_id": 0}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


def test_completion_consumer_requeues_handler_failure() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureCompletionConsumer(manager)
    message = _incoming_message(b'{"run_id": 8}')
    handler = AsyncMock(side_effect=RuntimeError("resume failed"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()
