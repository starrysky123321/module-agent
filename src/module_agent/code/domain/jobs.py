"""Contracts for asynchronous Code Agent execution."""

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from module_agent.code.domain.request import CodeAgentRequest


class ComputeTarget(StrEnum):
    """Worker pool required by a code job."""

    CPU = "cpu"
    GPU = "gpu"


class CodeJob(BaseModel):
    """Durable message consumed by a Code Worker."""

    request: CodeAgentRequest
    attempt: int = Field(ge=1)
    trace_id: UUID
    compute_target: ComputeTarget = ComputeTarget.CPU
    message_id: str | None = None


class CodeJobQueue(Protocol):
    """Publishes Code Agent work to a resource-specific queue."""

    async def enqueue(
        self,
        request: CodeAgentRequest,
        *,
        attempt: int,
        trace_id: UUID,
        compute_target: ComputeTarget = ComputeTarget.CPU,
    ) -> str:
        """Publish one persistent job and return its message id."""
        ...


CodeJobHandler = Callable[[CodeJob], Awaitable[None]]


class CodeJobConsumer(Protocol):
    """Consumes jobs for one configured resource pool."""

    async def run(self, handler: CodeJobHandler) -> None:
        """Consume until the process is stopped."""
        ...
