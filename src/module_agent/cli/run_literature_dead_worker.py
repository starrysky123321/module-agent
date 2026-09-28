import asyncio

from module_agent.literature.adapters.messaging.dead_letter_consumer import (
    RabbitMQLiteratureDeadConsumer,
)
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.shared.database.session import (
    database_engine,
    async_session_factory, 
)
from module_agent.literature.workers.dead_letter import LiteratureDeadWorker
from module_agent.bootstrap.worker_factories import build_literature_run_service
from module_agent.shared.llm.qwen_client import qwen_client_manager



async def run_worker() -> None:
    """执行当前任务。"""
    consumer = RabbitMQLiteratureDeadConsumer(
        rabbitmq_connection_manager
    )
    worker = LiteratureDeadWorker(
        consumer=consumer,
        session_factory=async_session_factory,
        run_service_factory=build_literature_run_service,
    )
    try:
        await worker.run()
    finally:
        await rabbitmq_connection_manager.close()
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
