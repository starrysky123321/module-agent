from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.literature.adapters.database.models.messaging import (
    LiteratureJobOutboxModel,
)
from module_agent.literature.adapters.database.models.run import LiteratureRunModel
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)
from module_agent.literature.application.run import LiteratureRunService
from module_agent.shared.idempotency import IdempotencyOperation, idempotency_key
from module_agent.shared.logging import logger
from module_agent.literature.domain.jobs import LiteratureJob
from module_agent.shared.exceptions import (
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
)


class SqlAlchemyLiteratureJobOutbox:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def dispatch(
        self,
        run_id: int,
        resume_workflow: bool = False,
        trace_id: UUID | None = None,
    ) -> str:
        key = idempotency_key(IdempotencyOperation.LITERATURE_DISPATCH, run_id)
        async with self.session_factory() as session, session.begin():
            # Serialize concurrent requests to enqueue the same run.
            locked_id = await session.scalar(
                select(LiteratureRunModel.id)
                .where(LiteratureRunModel.id == run_id)
                .with_for_update()
            )
            if locked_id is None:
                raise LiteratureRunNotFoundError(run_id)
            existing = await session.scalar(
                select(LiteratureJobOutboxModel).where(
                    LiteratureJobOutboxModel.run_id == run_id
                )
            )
            if existing is not None:
                if existing.resume_workflow != resume_workflow:
                    raise LiteratureRunStateError(run_id, "queue in a different mode")
                logger.info("reusing literature dispatch | idempotency_key={}", key)
                return existing.message_id

            await LiteratureRunService(
                SqlAlchemyLiteratureRunRepository(session)
            ).queue_run(run_id)
            message_id = uuid4().hex
            session.add(
                LiteratureJobOutboxModel(
                    message_id=message_id,
                    run_id=run_id,
                    resume_workflow=resume_workflow,
                    trace_id=trace_id,
                )
            )
        logger.info("literature dispatch recorded | idempotency_key={}", key)
        return message_id

    async def claim_next(self) -> LiteratureJob | None:
        """Lease one job in a short transaction before calling RabbitMQ."""
        async with self.session_factory() as session, session.begin():
            row = await session.scalar(
                select(LiteratureJobOutboxModel)
                .where(
                    LiteratureJobOutboxModel.published_at.is_(None),
                    LiteratureJobOutboxModel.available_at <= func.now(),
                )
                .order_by(
                    LiteratureJobOutboxModel.available_at,
                    LiteratureJobOutboxModel.message_id,
                )
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if row is None:
                return None
            await session.execute(
                update(LiteratureJobOutboxModel)
                .where(LiteratureJobOutboxModel.message_id == row.message_id)
                .values(available_at=func.now() + timedelta(seconds=30))
                .execution_options(synchronize_session=False)
            )
            return LiteratureJob(
                run_id=row.run_id,
                resume_workflow=row.resume_workflow,
                trace_id=row.trace_id,
                message_id=row.message_id,
            )

    async def mark_published(self, message_id: str) -> None:
        async with self.session_factory() as session, session.begin():
            await session.execute(
                update(LiteratureJobOutboxModel)
                .where(
                    LiteratureJobOutboxModel.message_id == message_id,
                    LiteratureJobOutboxModel.published_at.is_(None),
                )
                .values(published_at=func.now())
            )
