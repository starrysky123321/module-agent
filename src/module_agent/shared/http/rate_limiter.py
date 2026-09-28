import asyncio
import time


class AsyncRateLimiter:
    """封装 AsyncRateLimiter 相关的数据和行为。"""
    def __init__(self, min_interval_seconds: float) -> None:
        """初始化当前对象。"""
        if min_interval_seconds <= 0:
            raise ValueError("min_interval_seconds must be greater than 0")

        self._min_interval_seconds = min_interval_seconds
        self._last_allowed_at: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """等待到达下一次允许调用的时间。"""
        async with self._lock:
            now = time.monotonic()

            if self._last_allowed_at is not None:
                elapsed = now - self._last_allowed_at
                remaining = self._min_interval_seconds - elapsed

                if remaining > 0:
                    await asyncio.sleep(remaining)

            self._last_allowed_at = time.monotonic()
