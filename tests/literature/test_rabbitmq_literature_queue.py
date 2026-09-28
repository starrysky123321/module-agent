import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from module_agent.shared.messaging.rabbitmq import (
    RabbitMQConnectionManager,
)
from module_agent.literature.adapters.messaging.job_queue import (
    RabbitMQLiteratureJobQueue,
)


def test_connection_manager_rejects_empty_url() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        RabbitMQConnectionManager("   ")


def test_connection_manager_reuses_and_closes_connection() -> None:
    connection = MagicMock()
    connection.is_closed = False
    connection.close = AsyncMock()
    connect = AsyncMock(return_value=connection)
    manager = RabbitMQConnectionManager("amqp://example.test/vhost")

    async def exercise_manager() -> None:
        with patch(
            "module_agent.shared.messaging.rabbitmq.connect_robust",
            connect,
        ):
            first = await manager.get_connection()
            second = await manager.get_connection()
            assert first is second
            await manager.close()
            await manager.close()

    asyncio.run(exercise_manager())

    connect.assert_awaited_once_with("amqp://example.test/vhost")
    connection.close.assert_awaited_once_with()
    assert manager.connection is None


def test_literature_queue_publishes_run_id() -> None:
    exchange = MagicMock()
    exchange.publish = AsyncMock()
    channel = MagicMock()
    channel.declare_queue = AsyncMock(
        side_effect=[
            SimpleNamespace(name="literature.jobs.dead.v1"),
            SimpleNamespace(name="literature.jobs.v2"),
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
    queue = RabbitMQLiteratureJobQueue(manager)

    message_id = asyncio.run(queue.enqueue(42))

    assert isinstance(message_id, str)
    assert message_id
    connection.channel.assert_called_once_with(publisher_confirms=True)
    assert channel.declare_queue.await_args_list == [
        call(
            "literature.jobs.dead.v1",
            durable=True,
            arguments={"x-queue-type": "quorum"},
        ),
        call(
            "literature.jobs.v2",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-delivery-limit": 3,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "literature.jobs.dead.v1",
                "x-delayed-retry-type": "failed",
                "x-delayed-retry-min": 1000,
                "x-delayed-retry-max": 30000,
            },
        ),
    ]
    message = exchange.publish.await_args.args[0]
    assert json.loads(message.body.decode("utf-8")) == {
        "run_id": 42,
        "resume_workflow": False,
    }
    assert message.message_id == message_id
    exchange.publish.assert_awaited_once_with(
        message,
        routing_key="literature.jobs.v2",
        mandatory=True,
    )


def test_literature_queue_rejects_non_positive_run_id() -> None:
    manager = AsyncMock(spec=RabbitMQConnectionManager)
    queue = RabbitMQLiteratureJobQueue(manager)

    with pytest.raises(ValueError, match="must be positive"):
        asyncio.run(queue.enqueue(0))

    manager.get_connection.assert_not_awaited()
