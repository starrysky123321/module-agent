import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from aio_pika.abc import AbstractIncomingMessage

from module_agent.literature.domain.events import LiteratureCompletedEvent
from module_agent.shared.messaging.dead_letter_replay import (
    REPLAY_COUNT_HEADER,
    REPLAY_REASON_HEADER,
    RabbitMQDeadLetterReplayer,
)
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager


def _replayer(*, max_replays: int = 3) -> RabbitMQDeadLetterReplayer:
    return RabbitMQDeadLetterReplayer(
        AsyncMock(spec=RabbitMQConnectionManager),
        live_queue_name="completed.v1",
        dead_queue_name="completed.dead.v1",
        retry_queue_name="completed.retry.v1",
        parked_queue_name="completed.parked.v1",
        payload_validator=LiteratureCompletedEvent.model_validate_json,
        max_replays=max_replays,
        retry_delay_ms=5_000,
    )


def _message(
    body: bytes = b'{"run_id": 7}',
    *,
    headers: dict[str, object] | None = None,
) -> AsyncMock:
    message = AsyncMock(spec=AbstractIncomingMessage)
    message.body = body
    message.headers = headers or {}
    message.content_type = "application/json"
    message.message_id = "message-7"
    message.correlation_id = "correlation-7"
    return message


def test_dead_letter_is_delayed_before_replay() -> None:
    replayer = _replayer()
    message = _message()
    exchange = MagicMock()
    exchange.publish = AsyncMock()

    asyncio.run(replayer._process_message(message, exchange))

    published = exchange.publish.await_args.args[0]
    assert published.body == message.body
    assert published.headers == {REPLAY_COUNT_HEADER: 1}
    exchange.publish.assert_awaited_once_with(
        published,
        routing_key="completed.retry.v1",
        mandatory=True,
    )
    message.ack.assert_awaited_once_with()
    message.reject.assert_not_awaited()


def test_exhausted_dead_letter_is_parked() -> None:
    replayer = _replayer(max_replays=2)
    message = _message(headers={REPLAY_COUNT_HEADER: 2})
    exchange = MagicMock()
    exchange.publish = AsyncMock()

    asyncio.run(replayer._process_message(message, exchange))

    published = exchange.publish.await_args.args[0]
    assert published.headers == {
        REPLAY_COUNT_HEADER: 2,
        REPLAY_REASON_HEADER: "replay-limit-exceeded",
    }
    assert exchange.publish.await_args.kwargs["routing_key"] == (
        "completed.parked.v1"
    )
    message.ack.assert_awaited_once_with()


@pytest.mark.parametrize(
    ("body", "headers"),
    [
        (b"not-json", {}),
        (b'{"run_id": 7}', {REPLAY_COUNT_HEADER: "invalid"}),
    ],
)
def test_invalid_dead_letter_is_parked(
    body: bytes,
    headers: dict[str, object],
) -> None:
    replayer = _replayer()
    message = _message(body, headers=headers)
    exchange = MagicMock()
    exchange.publish = AsyncMock()

    asyncio.run(replayer._process_message(message, exchange))

    published = exchange.publish.await_args.args[0]
    assert published.headers[REPLAY_REASON_HEADER] == (
        "invalid-payload-or-replay-header"
    )
    assert exchange.publish.await_args.kwargs["routing_key"] == (
        "completed.parked.v1"
    )
    message.ack.assert_awaited_once_with()


def test_publish_failure_keeps_dead_letter_for_retry() -> None:
    replayer = _replayer()
    message = _message()
    exchange = MagicMock()
    exchange.publish = AsyncMock(side_effect=RuntimeError("broker down"))

    asyncio.run(replayer._process_message(message, exchange))

    message.reject.assert_awaited_once_with(requeue=True)
    message.ack.assert_not_awaited()


def test_recovery_topology_has_delay_and_parking_queue() -> None:
    replayer = _replayer()
    channel = MagicMock()
    channel.declare_queue = AsyncMock(
        side_effect=[
            SimpleNamespace(name="completed.v1"),
            SimpleNamespace(name="completed.dead.v1"),
            SimpleNamespace(name="completed.retry.v1"),
            SimpleNamespace(name="completed.parked.v1"),
        ]
    )

    queue = asyncio.run(replayer._declare_topology(channel))

    assert queue.name == "completed.dead.v1"
    assert channel.declare_queue.await_args_list == [
        call("completed.v1", durable=True, passive=True),
        call(
            "completed.dead.v1",
            durable=True,
            arguments={"x-queue-type": "quorum"},
        ),
        call(
            "completed.retry.v1",
            durable=True,
            arguments={
                "x-queue-type": "quorum",
                "x-message-ttl": 5_000,
                "x-dead-letter-exchange": "",
                "x-dead-letter-routing-key": "completed.v1",
            },
        ),
        call(
            "completed.parked.v1",
            durable=True,
            arguments={"x-queue-type": "quorum"},
        ),
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_replays": 0},
        {"retry_delay_ms": 999},
        {"retry_queue_name": "completed.v1"},
    ],
)
def test_replayer_rejects_unsafe_configuration(
    kwargs: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "live_queue_name": "completed.v1",
        "dead_queue_name": "completed.dead.v1",
        "retry_queue_name": "completed.retry.v1",
        "parked_queue_name": "completed.parked.v1",
        "payload_validator": LiteratureCompletedEvent.model_validate_json,
        "max_replays": 3,
        "retry_delay_ms": 5_000,
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        RabbitMQDeadLetterReplayer(
            AsyncMock(spec=RabbitMQConnectionManager),
            **values,  # type: ignore[arg-type]
        )
