"""Delete a task's durable records and its resumable workflow thread."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from module_agent.shared.exceptions import AppException
from module_agent.shared.logging import logger
from module_agent.workflow.state import validate_run_id, workflow_thread_id


class TaskDeletionRepository(Protocol):
    async def delete_if_inactive(self, run_id: int) -> None:
        """Delete related task records, rejecting queued or executing work."""
        ...


class TaskDeletionService:
    def __init__(
        self,
        repository: TaskDeletionRepository,
        delete_checkpoint: Callable[[str], Awaitable[None]],
    ) -> None:
        self.repository = repository
        self.delete_checkpoint = delete_checkpoint

    async def delete(self, run_id: int) -> None:
        """Delete idempotently; a checkpoint-cleanup failure can be retried."""
        validate_run_id(run_id)
        await self.repository.delete_if_inactive(run_id)
        # Commit relational deletion first: a storage outage must never destroy
        # the checkpoint of a task whose database deletion rolled back. Repeated
        # DELETE also cleans up a thread if the relational record is already gone.
        try:
            await self.delete_checkpoint(workflow_thread_id(run_id))
            await self.delete_checkpoint(workflow_thread_id(run_id, legacy=True))
        except Exception as exc:
            logger.warning("task checkpoint cleanup failed | run_id={} error_type={}", run_id, type(exc).__name__)
            raise AppException(
                "任务记录已删除，但恢复断点清理失败，请重试删除。",
                code="task_checkpoint_cleanup_pending",
                status_code=503,
                details={"run_id": run_id},
            ) from exc
