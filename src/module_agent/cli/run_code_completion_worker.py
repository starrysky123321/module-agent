"""Resume workflows when Code Workers publish completion events."""

import asyncio
import os
from prometheus_client import start_http_server
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.bootstrap.worker_factories import (
    build_module_workflow_coordinator,
)
from module_agent.code.adapters.messaging.completion import (
    RabbitMQCodeCompletionConsumer,
)
from module_agent.code.workers.completion import CodeCompletionWorker
from module_agent.code.domain.events import CodeCompletedEvent
from module_agent.shared.checkpoint.postgres import (
    postgres_checkpointer_manager,
)
from module_agent.shared.database.session import (
    async_session_factory,
    database_engine,
)
from module_agent.shared.messaging.rabbitmq import rabbitmq_connection_manager
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.code.adapters.github_client import github_client_manager
from module_agent.shared.decision.typesafe_client import typesafe_client_manager


async def run_worker() -> None:
    metrics_port = int(os.getenv("METRICS_PORT", "0"))
    if metrics_port:
        start_http_server(metrics_port)
    await postgres_checkpointer_manager.start()
    consumer = RabbitMQCodeCompletionConsumer(rabbitmq_connection_manager)

    async def handle(event: CodeCompletedEvent) -> None:
        async def resume(checkpointer: AsyncPostgresSaver) -> None:
            async with async_session_factory() as session:
                coordinator = build_module_workflow_coordinator(
                    session,
                    checkpointer,
                )
                worker = CodeCompletionWorker(
                    consumer=consumer,
                    workflow_service=coordinator.workflow_service,
                )
                await worker._handle(event)

        await postgres_checkpointer_manager.run_with_recovery(resume)

    try:
        await consumer.run(handle)
    finally:
        await postgres_checkpointer_manager.close()
        await rabbitmq_connection_manager.close()
        await github_client_manager.close()
        await qwen_client_manager.close()
        await typesafe_client_manager.close()
        await database_engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
