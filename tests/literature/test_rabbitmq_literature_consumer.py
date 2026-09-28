import asyncio
from unittest.mock import AsyncMock

import pytest
from aio_pika.abc import AbstractIncomingMessage

from module_agent.literature.domain.jobs import LiteratureJob
from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.job_consumer import (
    RabbitMQLiteratureJobConsumer,
)


def incoming_message(body: bytes) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    return message


def test_consumer_rejects_invalid_configuration() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)

    with pytest.raises(ValueError, match="queue_name"):
        RabbitMQLiteratureJobConsumer(manager, queue_name="   ")
    with pytest.raises(ValueError, match="prefetch_count"):
        RabbitMQLiteratureJobConsumer(manager, prefetch_count=0)


def test_consumer_acknowledges_successful_job() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureJobConsumer(manager)
    message = incoming_message(b'{"run_id": 8}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_awaited_once_with(LiteratureJob(run_id=8))
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()
    message.nack.assert_not_awaited()


def test_consumer_rejects_invalid_message_without_requeue() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureJobConsumer(manager)
    message = incoming_message(b'{"run_id": 0}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()
    message.nack.assert_not_awaited()


def test_consumer_requeues_failed_job() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureJobConsumer(manager)
    message = incoming_message(b'{"run_id": 8}')
    handler = AsyncMock(side_effect=RuntimeError("execution failed"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()
    message.nack.assert_not_awaited()
