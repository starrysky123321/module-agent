import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.literature.adapters.database.repositories.job_outbox import (
    SqlAlchemyLiteratureJobOutbox,
)
from module_agent.literature.domain.jobs import LiteratureJob, LiteratureJobQueue
from module_agent.literature.workers.outbox import LiteratureOutboxRelay


def test_relay_preserves_job_identity_and_marks_it_after_publish() -> None:
    outbox = AsyncMock(spec=SqlAlchemyLiteratureJobOutbox)
    queue = AsyncMock(spec=LiteratureJobQueue)
    trace_id = uuid4()
    outbox.claim_next.return_value = LiteratureJob(
        run_id=7,
        resume_workflow=True,
        trace_id=trace_id,
        message_id="persisted-id",
    )

    async def publish(*args, **kwargs):
        outbox.mark_published.assert_not_awaited()

    queue.enqueue.side_effect = publish
    assert asyncio.run(LiteratureOutboxRelay(outbox, queue).publish_next())
    queue.enqueue.assert_awaited_once_with(
        7,
        resume_workflow=True,
        trace_id=trace_id,
        message_id="persisted-id",
    )
    outbox.mark_published.assert_awaited_once_with("persisted-id")


def test_relay_keeps_failed_publish_pending() -> None:
    outbox = AsyncMock(spec=SqlAlchemyLiteratureJobOutbox)
    queue = AsyncMock(spec=LiteratureJobQueue)
    outbox.claim_next.return_value = LiteratureJob(run_id=7, message_id="persisted-id")
    queue.enqueue.side_effect = RuntimeError("RabbitMQ unavailable")

    with pytest.raises(RuntimeError, match="RabbitMQ unavailable"):
        asyncio.run(LiteratureOutboxRelay(outbox, queue).publish_next())

    outbox.mark_published.assert_not_awaited()


def test_relay_does_not_publish_when_outbox_is_empty() -> None:
    outbox = AsyncMock(spec=SqlAlchemyLiteratureJobOutbox)
    outbox.claim_next.return_value = None
    queue = AsyncMock(spec=LiteratureJobQueue)

    assert not asyncio.run(LiteratureOutboxRelay(outbox, queue).publish_next())
    queue.enqueue.assert_not_awaited()
