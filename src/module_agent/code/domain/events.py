"""Completion events emitted by Code Workers."""

from collections.abc import Awaitable, Callable
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field


class CodeCompletedEvent(BaseModel):
    """Signals that persisted CodeRun artifacts are ready."""

    literature_run_id: int = Field(gt=0)
    code_run_id: int = Field(gt=0)
    trace_id: UUID


class CodeCompletionPublisher(Protocol):
    """Publishes successful CodeRun completion events."""

    async def publish(self, event: CodeCompletedEvent) -> str:
        """Publish the event and return its message id."""
        ...


CodeCompletionHandler = Callable[[CodeCompletedEvent], Awaitable[None]]


class CodeCompletionConsumer(Protocol):
    """Consumes CodeRun completion events."""

    async def run(self, handler: CodeCompletionHandler) -> None:
        """Consume until the process is stopped."""
        ...
