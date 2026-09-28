from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from module_agent.shared.logging import logger
from module_agent.shared.database import database_engine
from module_agent.shared.cache.redis import redis_client
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.shared.checkpoint.postgres import (
    postgres_checkpointer_manager,
)
from module_agent.code.adapters.github_client import (
    github_client_manager,
)
from module_agent.shared.decision.typesafe_client import (
    typesafe_client_manager,
)
from module_agent.shared.config import (
    app_settings,
    validate_runtime_security,
)
from module_agent.literature.adapters.sources.http_client import (
    literature_http_client_manager,
)




@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """管理应用启动和关闭时的资源生命周期。"""
    validate_runtime_security(app_settings)
    logger.info("application starting")
    try:
        await postgres_checkpointer_manager.start()
        yield
    finally:
        await postgres_checkpointer_manager.close()
        await database_engine.dispose()
        await redis_client.aclose()
        await rabbitmq_connection_manager.close()
        await github_client_manager.close()
        await literature_http_client_manager.close()
        await qwen_client_manager.close()
        await typesafe_client_manager.close()
        
        logger.info("application stopping")
