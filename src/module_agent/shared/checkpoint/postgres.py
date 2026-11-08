"""Lifecycle and transient-recovery support for LangGraph checkpoints."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
import logging
from typing import TypeVar

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, OperationalError
from psycopg.rows import DictRow, dict_row
from psycopg_pool import AsyncConnectionPool

from module_agent.shared.config import app_settings


T = TypeVar("T")


class PostgresCheckpointerManager:
    """Own one saver pool and replace it after transient database failures."""

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url.strip()
        self._checkpointer: AsyncPostgresSaver | None = None
        self._pool: AsyncConnectionPool[AsyncConnection[DictRow]] | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger(__name__)

    async def start(self) -> AsyncPostgresSaver:
        """Start the saver once and reuse it while its pool is healthy."""
        if not self._database_url:
            raise RuntimeError(
                "PostgresCheckpointerManager must be started with a "
                "database URL"
            )
        if self._checkpointer is not None:
            return self._checkpointer

        async with self._lock:
            if self._checkpointer is None:
                await self._start_locked()
            assert self._checkpointer is not None
            return self._checkpointer

    def get_checkpointer(self) -> AsyncPostgresSaver:
        """Return the currently active saver."""
        if self._checkpointer is None:
            raise RuntimeError(
                "PostgresCheckpointerManager must be started before using it"
            )
        return self._checkpointer

    async def run_with_recovery(
        self,
        operation: Callable[[AsyncPostgresSaver], Awaitable[T]],
    ) -> T:
        """Retry one operation with a fresh saver after a connection failure."""
        checkpointer = await self.start()
        try:
            return await operation(checkpointer)
        except Exception as exc:
            if not _contains_operational_error(exc):
                raise
            self._logger.warning(
                "LangGraph checkpoint connection failed; rebuilding pool",
                exc_info=True,
            )

        checkpointer = await self.restart()
        return await operation(checkpointer)

    async def restart(self) -> AsyncPostgresSaver:
        """Close the old pool and create a replacement atomically."""
        async with self._lock:
            await self._close_locked(ignore_errors=True)
            await self._start_locked()
            assert self._checkpointer is not None
            return self._checkpointer

    async def close(self) -> None:
        """Close the current saver pool and release its context."""
        async with self._lock:
            await self._close_locked(ignore_errors=False)

    async def check_health(self) -> None:
        """Probe the same pool and schema used by compiled workflows, read-only."""
        if self._pool is None:
            raise RuntimeError("Checkpoint pool is not started")
        async with self._pool.connection() as connection:
            await connection.execute("SELECT 1 FROM checkpoints LIMIT 0")

    async def _start_locked(self) -> None:
        stack = AsyncExitStack()
        try:
            pool = await stack.enter_async_context(
                AsyncConnectionPool[AsyncConnection[DictRow]](
                    self._database_url,
                    min_size=1,
                    max_size=5,
                    timeout=3,
                    open=False,
                    kwargs={
                        "autocommit": True,
                        "prepare_threshold": 0,
                        "row_factory": dict_row,
                    },
                    check=AsyncConnectionPool[AsyncConnection[DictRow]].check_connection,
                )
            )
            await pool.wait(timeout=5)
            saver = AsyncPostgresSaver(pool)
        except BaseException:
            await stack.aclose()
            raise
        self._checkpointer = saver
        self._pool = pool
        self._exit_stack = stack

    async def _close_locked(self, *, ignore_errors: bool) -> None:
        stack = self._exit_stack
        self._checkpointer = None
        self._pool = None
        self._exit_stack = None
        if stack is None:
            return
        try:
            await stack.aclose()
        except Exception:
            if not ignore_errors:
                raise
            self._logger.warning(
                "Failed to close stale LangGraph checkpoint pool",
                exc_info=True,
            )


def _contains_operational_error(error: BaseException) -> bool:
    """Recognize psycopg connectivity errors through wrapper exceptions."""
    current: BaseException | None = error
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        if isinstance(current, OperationalError):
            return True
        visited.add(id(current))
        current = current.__cause__ or current.__context__
    return False


postgres_checkpointer_manager = PostgresCheckpointerManager(
    app_settings.langgraph_database_url
)
