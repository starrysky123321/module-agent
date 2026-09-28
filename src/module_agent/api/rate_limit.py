from collections.abc import Awaitable, Callable
from hashlib import sha256
from typing import Protocol, cast

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from module_agent.shared.config import AppSettings
from module_agent.shared.logging import logger


_INCREMENT_WINDOW = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


class RateLimitStore(Protocol):
    """Minimal Redis operation required by the HTTP limiter."""

    def eval(
        self,
        script: str,
        numkeys: int,
        *keys_and_args: str,
    ) -> Awaitable[object]: ...


def register_api_rate_limit_middleware(
    application: FastAPI,
    settings: AppSettings,
    store: RateLimitStore,
) -> None:
    """Register a Redis-backed fixed-window limiter when configured."""
    if not settings.api_rate_limit_enabled:
        return

    @application.middleware("http")
    async def api_rate_limit(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if _is_exempt(request, settings):
            return await call_next(request)

        client_host = request.client.host if request.client else "unknown"
        identity = sha256(client_host.encode("utf-8")).hexdigest()
        key = f"{settings.app_name}:api-rate-limit:{identity}"
        try:
            raw_result = await store.eval(
                _INCREMENT_WINDOW,
                1,
                key,
                str(settings.api_rate_limit_window_seconds),
            )
            result = cast(list[int], raw_result)
            count, ttl = int(result[0]), max(int(result[1]), 0)
        except Exception:
            logger.exception("api rate limit store unavailable")
            if settings.api_rate_limit_fail_open:
                return await call_next(request)
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Rate limit service is unavailable",
                    "code": "rate_limit_unavailable",
                },
                headers={"Retry-After": "1"},
            )

        limit = settings.api_rate_limit_requests
        headers = {
            "X-RateLimit-Limit": str(limit),
            "X-RateLimit-Remaining": str(max(limit - count, 0)),
            "X-RateLimit-Reset": str(ttl),
        }
        if count > limit:
            headers["Retry-After"] = str(max(ttl, 1))
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "API rate limit exceeded",
                    "code": "rate_limit_exceeded",
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response


def _is_exempt(request: Request, settings: AppSettings) -> bool:
    """Keep operational probes and API discovery outside the quota."""
    public_paths = {
        f"{settings.api_prefix}/health",
        f"{settings.api_prefix}/health/",
        f"{settings.api_prefix}/health/ready",
        "/metrics",
        "/docs",
        "/openapi.json",
    }
    return request.url.path in public_paths
