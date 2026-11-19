from typing import Protocol
from uuid import UUID


class LiteratureRunDispatcher(Protocol):
    """Durably schedule a literature job and return its message ID."""

    async def dispatch(
        self,
        run_id: int,
        resume_workflow: bool = False,
        trace_id: UUID | None = None,
    ) -> str: ...
