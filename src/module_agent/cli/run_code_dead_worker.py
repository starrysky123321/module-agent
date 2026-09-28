"""Run a Code Agent dead-letter recovery worker."""

import asyncio
import os

from module_agent.code.adapters.database.repositories.run import (
    TransactionalCodeRunRepository,
)
from module_agent.code.adapters.messaging.completion import (
    RabbitMQCodeCompletionPublisher,
)
from module_agent.code.adapters.messaging.dead_letter_consumer import (
    RabbitMQCodeDeadConsumer,
)
from module_agent.code.application.recovery import CodeRunRecoveryService
from module_agent.code.domain.jobs import ComputeTarget
from module_agent.code.workers.dead_letter import CodeDeadWorker
from module_agent.shared.database.session import (
    async_session_factory,
    database_engine,
)
from module_agent.shared.messaging.rabbitmq import rabbitmq_connection_manager


async def run_worker() -> None:
    target = ComputeTarget(os.getenv("CODE_WORKER_COMPUTE_TARGET", "cpu"))
    worker = CodeDeadWorker(
        consumer=RabbitMQCodeDeadConsumer(
            rabbitmq_connection_manager,
            compute_target=target,
        ),
        recovery_service=CodeRunRecoveryService(
            TransactionalCodeRunRepository(async_session_factory)
        ),
        completion_publisher=RabbitMQCodeCompletionPublisher(
            rabbitmq_connection_manager
        ),
    )
    try:
        await worker.run()
    finally:
        await rabbitmq_connection_manager.close()
        await database_engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
