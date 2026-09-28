"""Run a CPU or GPU Code Agent worker."""

import asyncio
import os
from prometheus_client import start_http_server

from module_agent.bootstrap.worker_factories import build_code_run_service
from module_agent.code.adapters.messaging.completion import (
    RabbitMQCodeCompletionPublisher,
)
from module_agent.code.adapters.messaging.job_consumer import (
    RabbitMQCodeJobConsumer,
)
from module_agent.code.domain.jobs import ComputeTarget
from module_agent.code.workers.code import CodeWorker
from module_agent.shared.database.session import database_engine
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.shared.messaging.rabbitmq import rabbitmq_connection_manager
from module_agent.code.adapters.github_client import github_client_manager


async def run_worker() -> None:
    metrics_port = int(os.getenv("METRICS_PORT", "0"))
    if metrics_port:
        start_http_server(metrics_port)
    target = ComputeTarget(os.getenv("CODE_WORKER_COMPUTE_TARGET", "cpu"))
    worker = CodeWorker(
        consumer=RabbitMQCodeJobConsumer(
            rabbitmq_connection_manager,
            compute_target=target,
            prefetch_count=int(os.getenv("CODE_WORKER_PREFETCH", "1")),
        ),
        run_service=build_code_run_service(),
        completion_publisher=RabbitMQCodeCompletionPublisher(
            rabbitmq_connection_manager
        ),
    )
    try:
        await worker.run()
    finally:
        await rabbitmq_connection_manager.close()
        await github_client_manager.close()
        await qwen_client_manager.close()
        await database_engine.dispose()


def main() -> None:
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
