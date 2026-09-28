import asyncio
from functools import partial

from module_agent.shared.checkpoint.postgres import (
    postgres_checkpointer_manager,
)
from module_agent.shared.database.session import (
    async_session_factory,
    database_engine,
)
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.literature.adapters.messaging.completion_consumer import (
    RabbitMQLiteratureCompletionConsumer,
)
from module_agent.bootstrap.worker_factories import (
    build_module_workflow_coordinator,
)
from module_agent.literature.workers.completion import (
    LiteratureCompletionWorker,
)

from module_agent.code.adapters.github_client import github_client_manager
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.shared.decision.typesafe_client import (
    typesafe_client_manager,
)


async def run_worker() -> None:
    """执行当前任务。"""
    checkpointer = await postgres_checkpointer_manager.start()
    consumer = RabbitMQLiteratureCompletionConsumer(
        rabbitmq_connection_manager
    )
    coordinator_factory = partial(
        build_module_workflow_coordinator,
        checkpointer=checkpointer,
    )
    worker = LiteratureCompletionWorker(
        consumer=consumer,
        session_factory=async_session_factory,
        coordinator_factory=coordinator_factory,
    )

    try:
        await worker.run()
    finally:
        await postgres_checkpointer_manager.close()
        await rabbitmq_connection_manager.close()
        await github_client_manager.close()
        await qwen_client_manager.close()
        await typesafe_client_manager.close()
        await database_engine.dispose()

def main() -> None:
    """运行命令行入口。"""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
