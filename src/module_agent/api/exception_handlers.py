from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from module_agent.shared.exceptions import (
    AppException,
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
)


async def handle_app_exception(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    """把业务异常转换为 HTTP 响应。"""
    assert isinstance(exc, AppException)
    content: dict[str, object] = {
        "detail": exc.message,
        "code": exc.code,
    }
    if exc.details is not None:
        content["details"] = exc.details
    return JSONResponse(
        status_code=exc.status_code,
        content=content,
    )


async def handle_literature_run_not_found(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    """把业务异常转换为 HTTP 响应。"""
    assert isinstance(exc, LiteratureRunNotFoundError)
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"detail": str(exc)},
    )


async def handle_literature_run_state_error(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    """把业务异常转换为 HTTP 响应。"""
    assert isinstance(exc, LiteratureRunStateError)
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


def register_exception_handlers(application: FastAPI) -> None:
    """注册对应组件。"""
    application.add_exception_handler(
        AppException,
        handle_app_exception,
    )
    application.add_exception_handler(
        LiteratureRunNotFoundError,
        handle_literature_run_not_found,
    )
    application.add_exception_handler(
        LiteratureRunStateError,
        handle_literature_run_state_error,
    )
