import re
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response

from module_agent.shared.context import observability_context
from module_agent.shared.logging import logger
from module_agent.shared.metrics import observe_http_request


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def register_request_context_middleware(application: FastAPI) -> None:
    """注册请求 ID、耗时和关联日志中间件。"""

    @application.middleware("http")
    async def request_context(
        request: Request,
        call_next,
    ) -> Response:
        """为一次 HTTP 请求建立可观测上下文。"""
        supplied = request.headers.get("X-Request-ID", "")
        request_id = (
            supplied
            if _SAFE_REQUEST_ID.fullmatch(supplied)
            else uuid4().hex
        )
        started = perf_counter()
        with observability_context(request_id=request_id):
            try:
                response = await call_next(request)
            except Exception:
                duration_seconds = perf_counter() - started
                route = getattr(request.scope.get("route"), "path", "unmatched")
                observe_http_request(
                    method=request.method,
                    route=route,
                    status=500,
                    duration_seconds=duration_seconds,
                )
                logger.exception(
                    "http request failed | method={} path={} duration_ms={:.2f}",
                    request.method,
                    request.url.path,
                    (perf_counter() - started) * 1000,
                )
                raise
            duration_seconds = perf_counter() - started
            route = getattr(request.scope.get("route"), "path", "unmatched")
            observe_http_request(
                method=request.method,
                route=route,
                status=response.status_code,
                duration_seconds=duration_seconds,
            )
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http request completed | method={} path={} status={} duration_ms={:.2f}",
                request.method,
                request.url.path,
                response.status_code,
                duration_seconds * 1000,
            )
            return response
