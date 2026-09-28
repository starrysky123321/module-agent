import asyncio
from unittest.mock import AsyncMock

import pytest
from aio_pika.abc import AbstractIncomingMessage

from module_agent.literature.domain.jobs import LiteratureJob
from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.dead_letter_consumer import (
    RabbitMQLiteratureDeadConsumer,
)


def incoming_message(body: bytes) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    return message


def test_dead_consumer_validates_and_normalizes_configuration() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)

    with pytest.raises(ValueError, match="dead_queue_name"):
        RabbitMQLiteratureDeadConsumer(manager, dead_queue_name="   ")
    with pytest.raises(ValueError, match="prefetch_count"):
        RabbitMQLiteratureDeadConsumer(manager, prefetch_count=0)

    consumer = RabbitMQLiteratureDeadConsumer(
        manager,
        dead_queue_name="  literature.jobs.dead.v1  ",
    )
    assert consumer.dead_queue_name == "literature.jobs.dead.v1"


def test_dead_consumer_acknowledges_successful_job() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureDeadConsumer(manager)
    message = incoming_message(b'{"run_id": 8}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_awaited_once_with(LiteratureJob(run_id=8))
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


def test_dead_consumer_discards_invalid_message() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureDeadConsumer(manager)
    message = incoming_message(b'{"run_id": 0}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)
    message.ack.assert_not_awaited()


def test_dead_consumer_requeues_job_when_handler_fails() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    consumer = RabbitMQLiteratureDeadConsumer(manager)
    message = incoming_message(b'{"run_id": 8}')
    handler = AsyncMock(side_effect=RuntimeError("database unavailable"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()
