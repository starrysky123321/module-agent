import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

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
from module_agent.literature.domain.events import (
    LiteratureCompletedEvent,
)

from module_agent.code.adapters.github_client import github_client_manager
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.shared.decision.typesafe_client import (
    typesafe_client_manager,
)


async def run_worker() -> None:
    """执行当前任务。"""
    await postgres_checkpointer_manager.start()
    consumer = RabbitMQLiteratureCompletionConsumer(
        rabbitmq_connection_manager
    )

    async def handle(event: LiteratureCompletedEvent) -> None:
        async def resume(checkpointer: AsyncPostgresSaver) -> None:
            async with async_session_factory() as session:
                async with session.begin():
                    coordinator = build_module_workflow_coordinator(
                        session,
                        checkpointer,
                    )
                    await coordinator.resume_after_literature_completion(
                        event.run_id
                    )

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
    """运行命令行入口。"""
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
