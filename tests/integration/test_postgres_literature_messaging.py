import asyncio
import os
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.literature.adapters.database.models.messaging import (
    LiteratureJobInboxModel,
    LiteratureJobOutboxModel,
)
from module_agent.literature.adapters.database.models.run import LiteratureRunModel
from module_agent.literature.adapters.database.repositories.job_outbox import (
    SqlAlchemyLiteratureJobOutbox,
)
from module_agent.literature.adapters.messaging.job_consumer import (
    RabbitMQLiteratureJobConsumer,
)
from module_agent.literature.adapters.messaging.job_queue import (
    RabbitMQLiteratureJobQueue,
)
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.workers.outbox import LiteratureOutboxRelay
from module_agent.literature.workers.search import LiteratureWorker
from module_agent.shared.config import app_settings
from module_agent.shared.database.session import create_database_engine
from module_agent.shared.messaging.rabbitmq import RabbitMQConnectionManager

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="requires a migrated PostgreSQL test database",
)


async def create_run(
    factory: async_sessionmaker[AsyncSession],
    status: LiteratureRunStatus = LiteratureRunStatus.PENDING,
) -> int:
    request = SearchRequest(
        topic="test delivery",
        description="synthetic messaging fixture",
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
        keywords=[],
        max_results=5,
    )
    async with factory() as session, session.begin():
        run = LiteratureRunModel(status=status, request=request.model_dump(mode="json"))
        session.add(run)
        await session.flush()
        return run.id


async def remove_runs(factory: async_sessionmaker[AsyncSession], *ids: int) -> None:
    async with factory() as session, session.begin():
        await session.execute(
            delete(LiteratureRunModel).where(LiteratureRunModel.id.in_(ids))
        )


def test_outbox_is_atomic_and_dispatch_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        engine = create_database_engine(app_settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        outbox = SqlAlchemyLiteratureJobOutbox(factory)
        run_id = await create_run(factory)
        other_id = await create_run(factory)
        try:
            first, second = await asyncio.gather(
                outbox.dispatch(run_id), outbox.dispatch(run_id)
            )
            assert second == first

            # The outbox insert fails after queue_run() has written QUEUED.
            monkeypatch.setattr(
                "module_agent.literature.adapters.database.repositories.job_outbox.uuid4",
                lambda: UUID(first),
            )
            with pytest.raises(IntegrityError):
                await outbox.dispatch(other_id)

            async with factory() as session:
                assert (
                    await session.get(LiteratureRunModel, run_id)
                ).status == LiteratureRunStatus.QUEUED
                assert (
                    await session.get(LiteratureRunModel, other_id)
                ).status == LiteratureRunStatus.PENDING
                assert (
                    await session.get(LiteratureJobOutboxModel, first)
                ).run_id == run_id
        finally:
            await remove_runs(factory, run_id, other_id)
            await engine.dispose()

    asyncio.run(exercise())


@pytest.mark.skipif(
    os.getenv("RUN_MESSAGING_INTEGRATION_TESTS") != "1",
    reason="requires a RabbitMQ test broker",
)
def test_publish_recovery_and_redelivery_after_worker_failure() -> None:
    async def exercise() -> None:
        engine = create_database_engine(app_settings.database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        outbox = SqlAlchemyLiteratureJobOutbox(factory)
        run_id = await create_run(factory)
        manager = RabbitMQConnectionManager(app_settings.rabbitmq_url)
        queue_name = f"literature.test.{uuid4().hex}"
        queue = RabbitMQLiteratureJobQueue(manager, queue_name)
        trace_id = uuid4()
        try:
            message_id = await outbox.dispatch(run_id, True, trace_id)
            failed_sender = AsyncMock()
            failed_sender.enqueue.side_effect = OSError("broker unavailable")
            with pytest.raises(OSError, match="broker unavailable"):
                await LiteratureOutboxRelay(outbox, failed_sender).publish_next()

            # Simulate waiting out the lease after a failed publisher.
            async with factory() as session, session.begin():
                row = await session.get(LiteratureJobOutboxModel, message_id)
                assert row.published_at is None
                await session.execute(
                    update(LiteratureJobOutboxModel)
                    .where(LiteratureJobOutboxModel.message_id == message_id)
                    .values(available_at=func.now())
                )

            assert await LiteratureOutboxRelay(
                SqlAlchemyLiteratureJobOutbox(factory), queue
            ).publish_next()
            await queue.enqueue(
                run_id, resume_workflow=True, trace_id=trace_id, message_id=message_id
            )

            executed = 0

            def executor_factory(session: AsyncSession):
                async def execute_started(_run):
                    nonlocal executed
                    executed += 1
                    await session.execute(
                        update(LiteratureRunModel)
                        .where(LiteratureRunModel.id == run_id)
                        .values(status=LiteratureRunStatus.COMPLETED)
                    )
                    if executed == 1:
                        raise RuntimeError("worker failed before commit")

                return SimpleNamespace(
                    get_run=AsyncMock(
                        return_value=SimpleNamespace(status=LiteratureRunStatus.RUNNING)
                    ),
                    start=AsyncMock(return_value=object()),
                    execute_started=execute_started,
                )

            consumer = RabbitMQLiteratureJobConsumer(manager, queue_name)
            publisher = AsyncMock()
            worker = LiteratureWorker(consumer, publisher, factory, executor_factory)
            connection = await manager.get_connection()
            async with connection.channel() as channel:
                rabbit_queue = await channel.get_queue(queue_name)
                delivery = await rabbit_queue.get(timeout=5)
                await consumer._process_message(delivery, worker._handle)
                async with factory() as session:
                    assert (
                        await session.get(LiteratureJobInboxModel, (run_id, message_id))
                        is None
                    )
                    assert (
                        await session.get(LiteratureRunModel, run_id)
                    ).status == LiteratureRunStatus.QUEUED
                for _ in range(2):
                    async with rabbit_queue.iterator() as messages:
                        delivery = await asyncio.wait_for(anext(messages), timeout=10)
                        await consumer._process_message(delivery, worker._handle)
                await rabbit_queue.delete(if_unused=False, if_empty=False)

            assert executed == 2
            async with factory() as session:
                assert (
                    await session.get(LiteratureJobInboxModel, (run_id, message_id))
                    is not None
                )
                assert (
                    await session.get(LiteratureRunModel, run_id)
                ).status == LiteratureRunStatus.COMPLETED
                assert (
                    await session.get(LiteratureJobOutboxModel, message_id)
                ).published_at is not None
        finally:
            await manager.close()
            await remove_runs(factory, run_id)
            await engine.dispose()

    asyncio.run(exercise())
