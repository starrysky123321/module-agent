from datetime import UTC, datetime
from uuid import UUID

from module_agent.code.domain import (
    CodeAgentRequest,
    CodeRun,
    CodeRunRepository,
    CodeRunStatus,
)


class CodeRunRecoveryService:
    """Convert an exhausted durable job into a terminal CodeRun."""

    def __init__(self, repository: CodeRunRepository) -> None:
        self.repository = repository

    async def fail_exhausted_execution(
        self,
        request: CodeAgentRequest,
        *,
        attempt: int,
        trace_id: UUID,
        error: str,
    ) -> CodeRun:
        """Persist FAILED after RabbitMQ has exhausted job delivery retries."""
        message = error.strip()
        if not message:
            raise ValueError("error must be non-empty")

        existing = await self.repository.get_by_execution(
            request.literature_run_id,
            attempt,
        )
        if existing is not None and existing.status in {
            CodeRunStatus.COMPLETED,
            CodeRunStatus.FAILED,
        }:
            return existing

        finished_at = datetime.now(UTC)
        if existing is None:
            failed = CodeRun(
                literature_run_id=request.literature_run_id,
                attempt=attempt,
                trace_id=trace_id,
                status=CodeRunStatus.FAILED,
                request=request,
                error=message[:1000],
                started_at=finished_at,
                finished_at=finished_at,
            )
        else:
            failed = CodeRun.model_validate(
                {
                    **existing.model_dump(),
                    "status": CodeRunStatus.FAILED,
                    "artifacts": [],
                    "error": message[:1000],
                    "finished_at": finished_at,
                }
            )
        return await self.repository.save(failed)
