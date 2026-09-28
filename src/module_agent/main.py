from fastapi import FastAPI

from module_agent.api.lifespan import lifespan
from module_agent.api.exception_handlers import register_exception_handlers
from module_agent.api.health import health_router
from module_agent.literature.api.source_search_router import source_search_router
from module_agent.shared.config import app_settings
from module_agent.literature.api.router import literature_router
from module_agent.code.api.router import code_router
from module_agent.validation.api.router import validation_router
from module_agent.workflow.api.router import workflow_router
from module_agent.supervision.api.router import supervision_router
from module_agent.api.request_context import (
    register_request_context_middleware,
)
from module_agent.api.auth import register_api_auth_middleware
from module_agent.api.metrics import metrics_router
from module_agent.api.audit import register_audit_middleware
from module_agent.api.rate_limit import register_api_rate_limit_middleware
from module_agent.shared.cache.redis import redis_client


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用。"""
    application = FastAPI(
        lifespan=lifespan,
        title=app_settings.app_name,
    )
    register_api_auth_middleware(application, app_settings)
    register_api_rate_limit_middleware(
        application,
        app_settings,
        redis_client,
    )
    register_audit_middleware(application)
    register_request_context_middleware(application)
    register_exception_handlers(application)
    application.include_router(metrics_router)
    application.include_router(health_router, prefix=app_settings.api_prefix)
    application.include_router(source_search_router, prefix=app_settings.api_prefix)
    application.include_router(literature_router, prefix=app_settings.api_prefix)
    application.include_router(code_router, prefix=app_settings.api_prefix)
    application.include_router(workflow_router, prefix=app_settings.api_prefix)
    application.include_router(
        supervision_router,
        prefix=app_settings.api_prefix,
    )
    application.include_router(
        validation_router,
        prefix=app_settings.api_prefix,
    )
    return application


app = create_app()
