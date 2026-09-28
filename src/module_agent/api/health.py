from fastapi import APIRouter

from module_agent.shared.config import app_settings


health_router = APIRouter(prefix="/health", tags=["health"])


@health_router.get("/")
async def health() -> dict[str, str]:
    """返回应用健康状态。"""
    return {
        "status": "ok",
        "service": app_settings.app_name,
        "environment": app_settings.app_env,
    }
