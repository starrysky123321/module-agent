"""Cooperatively stop async work when durable cancellation/deadline changes."""

import asyncio
from collections.abc import Awaitable, Callable
import math
from typing import TypeVar

T = TypeVar("T")


class ExecutionStopped(RuntimeError):
    """任务已被持久化控制面停止。"""


async def run_with_control(
    operation: Callable[[], Awaitable[T]],
    control: Callable[[], Awaitable[bool]] | None,
    *,
    poll_seconds: float = 1.0,
) -> T:
    """取消正在等待的本地协程，并等待其子进程/HTTP 清理完成。"""
    if not math.isfinite(poll_seconds) or poll_seconds <= 0:
        raise ValueError("Control interval must be finite and positive")
    if control is None:
        return await operation()
    if not await control():
        raise ExecutionStopped("任务已取消或超时，未启动处理。")

    async def execute() -> T:
        return await operation()

    task = asyncio.create_task(execute())
    try:
        while True:
            done, _ = await asyncio.wait({task}, timeout=poll_seconds)
            if done:
                return task.result()
            if not await control():
                raise ExecutionStopped(
                    "任务已取消或超时，已停止本机处理。已发送的外部模型请求仍可能计费。"
                )
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
