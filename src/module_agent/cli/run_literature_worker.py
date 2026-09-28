import asyncio
import os
from prometheus_client import start_http_server

from module_agent.shared.cache.redis import redis_client
from module_agent.shared.database.session import (
    async_session_factory,
    database_engine,
)
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.literature.adapters.messaging.job_consumer import (
    RabbitMQLiteratureJobConsumer,
)
from module_agent.literature.adapters.messaging.completion_publisher import (
    RabbitMQLiteratureCompletionPublisher,
)
from module_agent.bootstrap.worker_factories import build_literature_run_executor
from module_agent.literature.workers.search import LiteratureWorker
from module_agent.shared.llm.qwen_client import qwen_client_manager

async def run_worker() -> None:
    """执行当前任务。"""
    metrics_port = int(os.getenv("METRICS_PORT", "0"))
    if metrics_port:
        start_http_server(metrics_port)
    consumer = RabbitMQLiteratureJobConsumer(
        rabbitmq_connection_manager
    )
    completion_publisher = RabbitMQLiteratureCompletionPublisher(
        rabbitmq_connection_manager
    )
    worker = LiteratureWorker(
        consumer=consumer,
        completion_publisher=completion_publisher,
        session_factory=async_session_factory,
        executor_factory=build_literature_run_executor,
    )

    try:
        await worker.run()
    finally:
        await rabbitmq_connection_manager.close()
        await redis_client.aclose()
        await database_engine.dispose()
        await qwen_client_manager.close()

def main() -> None:
    """运行命令行入口。"""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass



if __name__ == "__main__":
    main()
