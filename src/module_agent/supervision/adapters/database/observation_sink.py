from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
)

from module_agent.supervision.adapters.database.repositories.observation import (
    SqlAlchemySupervisorObservationRepository,
)
from module_agent.supervision.domain import (
    SupervisorFailureObservation,
)
from module_agent.shared.logging import logger


class SqlAlchemySupervisorObservationSink:
    """Persist shadow telemetry in a transaction isolated from the workflow."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """初始化当前对象。"""
        self.session_factory = session_factory

    async def record(
        self,
        observation: SupervisorFailureObservation,
    ) -> None:
        """记录本次观察结果。"""
        try:
            async with self.session_factory() as session:
                async with session.begin():
                    repository = (
                        SqlAlchemySupervisorObservationRepository(
                            session
                        )
                    )
                    await repository.add(observation)
        except Exception:
            logger.exception(
                "supervisor observation persistence failed | run_id={}",
                observation.literature_run_id,
            )
            raise
