from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response

from module_agent.shared.logging import logger


def register_audit_middleware(application: FastAPI) -> None:
    """Record one security-safe audit event for every HTTP request."""

    @application.middleware("http")
    async def audit_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        started = perf_counter()
        status = 500
        outcome = "failed"
        try:
            response = await call_next(request)
            status = response.status_code
            outcome = "accepted" if status < 400 else "rejected"
            return response
        finally:
            client = request.client.host if request.client else "unknown"
            authenticated = bool(
                getattr(request.state, "authenticated", False)
            )
            logger.info(
                "audit event | action=http_request method={} path={} "
                "status={} outcome={} principal={} client={} duration_ms={:.2f}",
                request.method,
                request.url.path,
                status,
                outcome,
                "api_token" if authenticated else "anonymous",
                client,
                (perf_counter() - started) * 1000,
            )
