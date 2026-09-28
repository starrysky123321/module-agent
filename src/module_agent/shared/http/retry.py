import asyncio
import math
from collections.abc import Awaitable, Callable

import httpx


type HttpOperation = Callable[
    [],
    Awaitable[httpx.Response],
]


RETRYABLE_STATUS_CODES = frozenset(
    {
        429,
        500,
        502,
        503,
        504,
    }
)


class AsyncHttpRetry:
    """封装 AsyncHttpRetry 相关的数据和行为。"""
    def __init__(
        self,
        max_attempts: int = 4,
        base_delay_seconds: float = 2.0,
    ) -> None:
        """初始化当前对象。"""
        if max_attempts < 1:
            raise ValueError(
                "max_attempts must be greater than or equal to 1"
            )

        if base_delay_seconds <= 0:
            raise ValueError(
                "base_delay_seconds must be greater than 0"
            )

        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds

    async def execute(
        self,
        operation: HttpOperation,
    ) -> httpx.Response:
        """执行当前用例。"""
        attempt_index = 0

        while True:
            response = await operation()

            # 不需要重试，直接返回
            if (
                response.status_code
                not in RETRYABLE_STATUS_CODES
            ):
                return response

            # 已经是最后一次，直接返回失败响应
            if attempt_index + 1 >= self.max_attempts:
                return response

            retry_after = self._parse_retry_after(
                response.headers.get("Retry-After")
            )

            if retry_after is not None:
                delay = retry_after
            else:
                delay = (
                    self.base_delay_seconds
                    * (2**attempt_index)
                )

            await asyncio.sleep(delay)
            attempt_index += 1

    @staticmethod
    def _parse_retry_after(
        value: str | None,
    ) -> float | None:
        if value is None:
            return None

        try:
            seconds = float(value)
        except ValueError:
            return None

        # 排除负数、NaN和Infinity
        if seconds < 0 or not math.isfinite(seconds):
            return None

        return seconds
