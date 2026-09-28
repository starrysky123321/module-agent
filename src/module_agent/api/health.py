import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from module_agent.shared.config import app_settings
from module_agent.shared.database import database_engine
from module_agent.shared.cache.redis import redis_client
from module_agent.shared.logging import logger
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)


health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/")
async def health() -> dict[str, str]:
    """Report process liveness without touching external dependencies."""
    return {
        "status": "ok",
        "service": app_settings.app_name,
        "environment": app_settings.app_env,
    }


@health_router.get("/ready", response_model=None)
async def readiness() -> dict[str, object] | JSONResponse:
    """Report whether required infrastructure can serve real work."""
    names = tuple(_DEPENDENCY_PROBES)
    states = await asyncio.gather(
        *(
            _run_probe(name, _DEPENDENCY_PROBES[name])
            for name in names
        )
    )
    dependencies = dict(zip(names, states, strict=True))
    ready = all(state == "ok" for state in dependencies.values())
    payload: dict[str, object] = {
        "status": "ready" if ready else "not_ready",
        "service": app_settings.app_name,
        "dependencies": dependencies,
    }
    if ready:
        return payload
    return JSONResponse(status_code=503, content=payload)


async def _check_database() -> None:
    async with database_engine.connect() as connection:
        _ = await connection.execute(text("SELECT 1"))


async def _check_redis() -> None:
    _ = await redis_client.ping()


async def _check_rabbitmq() -> None:
    _ = await rabbitmq_connection_manager.get_connection()


async def _run_probe(
    name: str,
    probe: Callable[[], Awaitable[None]],
) -> str:
    try:
        await asyncio.wait_for(
            probe(),
            timeout=app_settings.health_dependency_timeout_seconds,
        )
    except Exception as exc:
        logger.warning(
            "readiness dependency unavailable | dependency={} error_type={}",
            name,
            type(exc).__name__,
        )
        return "unavailable"
    return "ok"


_DEPENDENCY_PROBES: dict[str, Callable[[], Awaitable[None]]] = {
    "postgres": _check_database,
    "redis": _check_redis,
    "rabbitmq": _check_rabbitmq,
}
