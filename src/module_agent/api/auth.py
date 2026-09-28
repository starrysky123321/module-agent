from hmac import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from module_agent.shared.config import AppSettings


def register_api_auth_middleware(
    application: FastAPI,
    settings: AppSettings,
) -> None:
    """注册生产环境 Bearer Token 鉴权中间件。"""

    @application.middleware("http")
    async def api_auth(request: Request, call_next):
        """校验当前 HTTP 请求是否携带有效凭据。"""
        if not _requires_authentication(request, settings):
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        expected = settings.api_auth_token.strip()
        if (
            scheme.lower() != "bearer"
            or not supplied
            or not compare_digest(supplied, expected)
        ):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Valid bearer authentication is required",
                    "code": "authentication_required",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)


def _requires_authentication(
    request: Request,
    settings: AppSettings,
) -> bool:
    if settings.app_env.lower() != "production":
        return False
    public_paths = {
        f"{settings.api_prefix}/health/",
        f"{settings.api_prefix}/health",
        "/docs",
        "/openapi.json",
        "/metrics",
    }
    return request.url.path not in public_paths
