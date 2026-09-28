"""Replay transient workflow completion dead letters with bounded retries."""

import asyncio

from module_agent.code.domain.events import CodeCompletedEvent
from module_agent.literature.domain.events import LiteratureCompletedEvent
from module_agent.shared.config import app_settings
from module_agent.shared.messaging.dead_letter_replay import (
    RabbitMQDeadLetterReplayer,
)
from module_agent.shared.messaging.rabbitmq import rabbitmq_connection_manager


async def run_worker() -> None:
    """Run Literature and Code completion recovery consumers together."""
    literature = RabbitMQDeadLetterReplayer(
        rabbitmq_connection_manager,
        live_queue_name="literature.completed.v1",
        dead_queue_name="literature.completed.dead.v1",
        retry_queue_name="literature.completed.retry.v1",
        parked_queue_name="literature.completed.parked.v1",
        payload_validator=LiteratureCompletedEvent.model_validate_json,
        max_replays=app_settings.completion_dead_letter_replay_limit,
        retry_delay_ms=app_settings.completion_dead_letter_retry_delay_ms,
    )
    code = RabbitMQDeadLetterReplayer(
        rabbitmq_connection_manager,
        live_queue_name="code.completed.v1",
        dead_queue_name="code.completed.dead.v1",
        retry_queue_name="code.completed.retry.v1",
        parked_queue_name="code.completed.parked.v1",
        payload_validator=CodeCompletedEvent.model_validate_json,
        max_replays=app_settings.completion_dead_letter_replay_limit,
        retry_delay_ms=app_settings.completion_dead_letter_retry_delay_ms,
    )
    try:
        await asyncio.gather(literature.run(), code.run())
    finally:
        await rabbitmq_connection_manager.close()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
