"""Worker that resumes LangGraph after Code Agent completion."""

from module_agent.code.domain.events import (
    CodeCompletedEvent,
    CodeCompletionConsumer,
)
from module_agent.shared.context import observability_context
from module_agent.shared.metrics import QUEUE_JOBS
from module_agent.workflow.service import ModuleWorkflowService


class CodeCompletionWorker:
    """Translate CodeRun completion events into graph resume commands."""

    def __init__(
        self,
        *,
        consumer: CodeCompletionConsumer,
        workflow_service: ModuleWorkflowService,
    ) -> None:
        self.consumer = consumer
        self.workflow_service = workflow_service

    async def run(self) -> None:
        await self.consumer.run(self._handle)

    async def _handle(self, event: CodeCompletedEvent) -> None:
        with observability_context(
            trace_id=event.trace_id,
            workflow_id=event.literature_run_id,
        ):
            try:
                await self.workflow_service.resume_code_workflow(
                    event.literature_run_id,
                    event.code_run_id,
                )
            except Exception:
                QUEUE_JOBS.labels(
                    queue="code.completed.v1", outcome="failed"
                ).inc()
                raise
            QUEUE_JOBS.labels(
                queue="code.completed.v1", outcome="completed"
            ).inc()
