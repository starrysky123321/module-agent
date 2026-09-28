import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from aio_pika.abc import AbstractIncomingMessage

from module_agent.code.adapters.messaging.completion import (
    RabbitMQCodeCompletionConsumer,
    RabbitMQCodeCompletionPublisher,
)
from module_agent.code.adapters.messaging.job_consumer import (
    RabbitMQCodeJobConsumer,
)
from module_agent.code.adapters.messaging.job_queue import RabbitMQCodeJobQueue
from module_agent.code.domain import CodeAgentRequest, CodePaperInput
from module_agent.code.domain.events import CodeCompletedEvent
from module_agent.code.domain.jobs import CodeJob, ComputeTarget
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


TRACE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _request() -> CodeAgentRequest:
    return CodeAgentRequest(
        literature_run_id=7,
        papers=[
            CodePaperInput(
                paper_id=51,
                source="openalex",
                source_id="W51",
                title="Paper 51",
            )
        ],
    )


def _message(body: bytes) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    message.message_id = "broker-message-id"
    return message


def _publisher_dependencies() -> tuple[AsyncMock, MagicMock, AsyncMock]:
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.default_exchange = exchange
    channel.declare_queue = AsyncMock(
        side_effect=[
            SimpleNamespace(name="dead"),
            SimpleNamespace(name="target"),
        ]
    )
    channel_context = MagicMock()
    channel_context.__aenter__ = AsyncMock(return_value=channel)
    channel_context.__aexit__ = AsyncMock(return_value=None)
    connection = MagicMock()
    connection.channel.return_value = channel_context
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    manager.get_connection.return_value = connection
    return manager, channel, exchange.publish


def test_job_publisher_emits_persistent_validated_job() -> None:
    manager, _, publish = _publisher_dependencies()
    queue = RabbitMQCodeJobQueue(manager)

    message_id = asyncio.run(
        queue.enqueue(
            _request(),
            attempt=2,
            trace_id=TRACE_ID,
            compute_target=ComputeTarget.GPU,
        )
    )

    message = publish.await_args.args[0]
    payload = json.loads(message.body)
    assert payload["attempt"] == 2
    assert payload["compute_target"] == "gpu"
    assert message.message_id == message_id
    assert publish.await_args.kwargs == {
        "routing_key": "target",
        "mandatory": True,
    }


def test_completion_publisher_emits_persistent_event() -> None:
    manager, _, publish = _publisher_dependencies()
    publisher = RabbitMQCodeCompletionPublisher(manager)
    event = CodeCompletedEvent(
        literature_run_id=7,
        code_run_id=3,
        trace_id=TRACE_ID,
    )

    message_id = asyncio.run(publisher.publish(event))

    message = publish.await_args.args[0]
    assert CodeCompletedEvent.model_validate_json(message.body) == event
    assert message.message_id == message_id
    assert publish.await_args.kwargs == {
        "routing_key": "target",
        "mandatory": True,
    }


def test_job_consumer_acknowledges_valid_job() -> None:
    consumer = RabbitMQCodeJobConsumer(
        AsyncMock(spec=RabbitMQConnectionManager),
        compute_target=ComputeTarget.CPU,
    )
    job = CodeJob(request=_request(), attempt=1, trace_id=TRACE_ID)
    message = _message(job.model_dump_json().encode())
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handled = handler.await_args.args[0]
    assert handled.message_id == "broker-message-id"
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


@pytest.mark.parametrize(
    "body",
    [
        b"not-json",
        CodeJob(
            request=_request(),
            attempt=1,
            trace_id=TRACE_ID,
            compute_target=ComputeTarget.GPU,
        ).model_dump_json().encode(),
    ],
)
def test_job_consumer_discards_invalid_or_misrouted_job(body: bytes) -> None:
    consumer = RabbitMQCodeJobConsumer(
        AsyncMock(spec=RabbitMQConnectionManager),
        compute_target=ComputeTarget.CPU,
    )
    message = _message(body)
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)


def test_job_consumer_requeues_handler_failure() -> None:
    consumer = RabbitMQCodeJobConsumer(
        AsyncMock(spec=RabbitMQConnectionManager),
        compute_target=ComputeTarget.CPU,
    )
    job = CodeJob(request=_request(), attempt=1, trace_id=TRACE_ID)
    message = _message(job.model_dump_json().encode())
    handler = AsyncMock(side_effect=RuntimeError("worker unavailable"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()


def test_completion_consumer_acknowledges_valid_event() -> None:
    consumer = RabbitMQCodeCompletionConsumer(
        AsyncMock(spec=RabbitMQConnectionManager)
    )
    event = CodeCompletedEvent(
        literature_run_id=7,
        code_run_id=3,
        trace_id=TRACE_ID,
    )
    message = _message(event.model_dump_json().encode())
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_awaited_once_with(event)
    message.ack.assert_awaited_once_with()


def test_completion_consumer_rejects_invalid_event() -> None:
    consumer = RabbitMQCodeCompletionConsumer(
        AsyncMock(spec=RabbitMQConnectionManager)
    )
    message = _message(b'{"literature_run_id": 0}')
    handler = AsyncMock()

    asyncio.run(consumer._process_message(message, handler))

    handler.assert_not_awaited()
    message.reject.assert_awaited_once_with(requeue=False)


def test_completion_consumer_requeues_handler_failure() -> None:
    consumer = RabbitMQCodeCompletionConsumer(
        AsyncMock(spec=RabbitMQConnectionManager)
    )
    event = CodeCompletedEvent(
        literature_run_id=7,
        code_run_id=3,
        trace_id=TRACE_ID,
    )
    message = _message(event.model_dump_json().encode())
    handler = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))

    asyncio.run(consumer._process_message(message, handler))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()
