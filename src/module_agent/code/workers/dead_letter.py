"""Worker that terminalizes Code Agent jobs after retry exhaustion."""

from module_agent.code.application.recovery import CodeRunRecoveryService
from module_agent.code.domain.events import (
    CodeCompletedEvent,
    CodeCompletionPublisher,
)
from module_agent.code.domain.jobs import CodeJob, CodeJobConsumer
from module_agent.shared.context import observability_context


class CodeDeadWorker:
    """Mark an exhausted CodeRun failed and resume its workflow."""

    def __init__(
        self,
        *,
        consumer: CodeJobConsumer,
        recovery_service: CodeRunRecoveryService,
        completion_publisher: CodeCompletionPublisher,
    ) -> None:
        self.consumer = consumer
        self.recovery_service = recovery_service
        self.completion_publisher = completion_publisher

    async def run(self) -> None:
        await self.consumer.run(self._handle)

    async def _handle(self, job: CodeJob) -> None:
        with observability_context(
            trace_id=job.trace_id,
            workflow_id=job.request.literature_run_id,
            message_id=job.message_id,
        ):
            run = await self.recovery_service.fail_exhausted_execution(
                job.request,
                attempt=job.attempt,
                trace_id=job.trace_id,
                error="Code job exceeded RabbitMQ delivery limit",
            )
            if run.id is None:
                raise RuntimeError("Recovered CodeRun has no id")
            await self.completion_publisher.publish(
                CodeCompletedEvent(
                    literature_run_id=job.request.literature_run_id,
                    code_run_id=run.id,
                    trace_id=job.trace_id,
                )
            )
