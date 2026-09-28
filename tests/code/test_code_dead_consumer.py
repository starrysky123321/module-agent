import asyncio
from unittest.mock import AsyncMock

from aio_pika.abc import AbstractIncomingMessage

from module_agent.code.adapters.messaging.dead_letter_consumer import (
    RabbitMQCodeDeadConsumer,
)
from module_agent.code.domain.jobs import CodeJob, ComputeTarget
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


def _message(body: bytes) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    return message


def _consumer() -> RabbitMQCodeDeadConsumer:
    return RabbitMQCodeDeadConsumer(
        AsyncMock(spec=RabbitMQConnectionManager),
        compute_target=ComputeTarget.CPU,
    )


def test_dead_consumer_acknowledges_valid_job() -> None:
    consumer = _consumer()
    message = _message(
        b'{"request":{"literature_run_id":7,"papers":'
        b'[{"paper_id":51,"source":"openalex","source_id":"W51",'
        b'"title":"Paper 51"}]},"attempt":1,'
        b'"trace_id":"00000000-0000-0000-0000-000000000001",'
        b'"compute_target":"cpu"}'
    )
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    assert isinstance(handler.await_args.args[0], CodeJob)
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


def test_dead_consumer_discards_invalid_job() -> None:
    consumer = _consumer()
    message = _message(b"not-json")
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)


def test_dead_consumer_requeues_handler_failure() -> None:
    consumer = _consumer()
    message = _message(
        b'{"request":{"literature_run_id":7,"papers":'
        b'[{"paper_id":51,"source":"openalex","source_id":"W51",'
        b'"title":"Paper 51"}]},"attempt":1,'
        b'"trace_id":"00000000-0000-0000-0000-000000000001",'
        b'"compute_target":"cpu"}'
    )
    handler = AsyncMock(side_effect=RuntimeError("database unavailable"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()
