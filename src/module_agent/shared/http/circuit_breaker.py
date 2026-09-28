import asyncio
import time
from collections.abc import Callable


class CircuitOpenError(RuntimeError):
    """Raised when a protected operation is temporarily disabled."""

    def __init__(self) -> None:
        """初始化当前对象。"""
        super().__init__("HTTP circuit breaker is open")


class AsyncCircuitBreaker:
    """封装 AsyncCircuitBreaker 相关的数据和行为。"""
    def __init__(
        self,
        failure_threshold: int,
        recovery_timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """初始化当前对象。"""
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be greater than or equal to 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be greater than 0")

        self._failure_threshold = failure_threshold
        self._recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._probe_in_flight = False
        self._lock = asyncio.Lock()

    async def before_call(self) -> None:
        """在外部调用前检查熔断器状态。"""
        async with self._lock:
            if self._opened_at is None:
                return

            elapsed = self._clock() - self._opened_at
            if elapsed < self._recovery_timeout_seconds:
                raise CircuitOpenError()

            # Only one request may probe a service after the cooldown.
            if self._probe_in_flight:
                raise CircuitOpenError()

            self._probe_in_flight = True

    async def record_success(self) -> None:
        """记录一次成功调用。"""
        async with self._lock:
            self._consecutive_failures = 0
            self._opened_at = None
            self._probe_in_flight = False

    async def record_failure(self) -> None:
        """记录一次失败调用。"""
        async with self._lock:
            self._consecutive_failures += 1

            if (
                self._probe_in_flight
                or self._consecutive_failures >= self._failure_threshold
            ):
                self._opened_at = self._clock()

            self._probe_in_flight = False
