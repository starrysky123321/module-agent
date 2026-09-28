"""Independent worker that executes durable Code Agent jobs."""

from module_agent.code.application.run import CodeRunService
from module_agent.code.domain.events import (
    CodeCompletedEvent,
    CodeCompletionPublisher,
)
from module_agent.code.domain.jobs import CodeJob, CodeJobConsumer
from module_agent.shared.context import observability_context
from module_agent.shared.metrics import QUEUE_JOBS


class CodeWorker:
    """Execute CodeRunService outside the API process."""

    def __init__(
        self,
        *,
        consumer: CodeJobConsumer,
        run_service: CodeRunService,
        completion_publisher: CodeCompletionPublisher,
    ) -> None:
        self.consumer = consumer
        self.run_service = run_service
        self.completion_publisher = completion_publisher

    async def run(self) -> None:
        await self.consumer.run(self._handle)

    async def _handle(self, job: CodeJob) -> None:
        queue_name = f"code.jobs.{job.compute_target.value}.v1"
        with observability_context(
            trace_id=job.trace_id,
            workflow_id=job.request.literature_run_id,
            message_id=job.message_id,
        ):
            try:
                run = await self.run_service.execute(
                    job.request,
                    attempt=job.attempt,
                    trace_id=job.trace_id,
                )
                if run.id is None:
                    raise RuntimeError("Persisted CodeRun has no id")
                await self.completion_publisher.publish(
                    CodeCompletedEvent(
                        literature_run_id=job.request.literature_run_id,
                        code_run_id=run.id,
                        trace_id=job.trace_id,
                    )
                )
            except Exception:
                QUEUE_JOBS.labels(queue=queue_name, outcome="failed").inc()
                failed = await self.run_service.repository.get_by_execution(
                    job.request.literature_run_id,
                    job.attempt,
                )
                if failed is None or failed.id is None:
                    raise
                await self.completion_publisher.publish(
                    CodeCompletedEvent(
                        literature_run_id=job.request.literature_run_id,
                        code_run_id=failed.id,
                        trace_id=job.trace_id,
                    )
                )
                return
            QUEUE_JOBS.labels(queue=queue_name, outcome="completed").inc()
