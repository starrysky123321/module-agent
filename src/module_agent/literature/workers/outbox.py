import asyncio
import logging

from module_agent.literature.adapters.database.repositories.job_outbox import (
    SqlAlchemyLiteratureJobOutbox,
)
from module_agent.literature.domain.jobs import LiteratureJobQueue


logger = logging.getLogger(__name__)


class LiteratureOutboxRelay:
    def __init__(
        self, outbox: SqlAlchemyLiteratureJobOutbox, queue: LiteratureJobQueue
    ) -> None:
        self.outbox = outbox
        self.queue = queue

    async def publish_next(self) -> bool:
        job = await self.outbox.claim_next()
        if job is None:
            return False
        assert job.message_id is not None
        await asyncio.wait_for(
            self.queue.enqueue(
                job.run_id,
                resume_workflow=job.resume_workflow,
                trace_id=job.trace_id,
                message_id=job.message_id,
            ),
            timeout=10,
        )
        await self.outbox.mark_published(job.message_id)
        return True

    async def run(self) -> None:
        while True:
            try:
                if await self.publish_next():
                    continue
            except Exception:
                logger.exception("Could not relay a literature outbox message")
            await asyncio.sleep(1)
