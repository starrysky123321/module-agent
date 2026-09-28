from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from module_agent.validation.adapters.database.models.run import (
    ValidationRunModel,
    ValidationRunReportModel,
)
from module_agent.validation.domain import (
    ValidationReport,
    ValidationRequest,
    ValidationRun,
    ValidationRunStatus,
)


class SqlAlchemyValidationRunRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session

    async def get_by_id(self, run_id: int) -> ValidationRun | None:
        """获取对应记录。"""
        return await self._get_one(ValidationRunModel.id == run_id)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> ValidationRun | None:
        """获取对应记录。"""
        return await self._get_one(
            ValidationRunModel.literature_run_id == literature_run_id,
            ValidationRunModel.attempt == attempt,
        )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[ValidationRun]:
        """列出符合条件的记录。"""
        statement = (
            select(ValidationRunModel)
            .options(selectinload(ValidationRunModel.reports))
            .where(
                ValidationRunModel.literature_run_id
                == literature_run_id
            )
            .order_by(ValidationRunModel.attempt, ValidationRunModel.id)
        )
        result = await self.session.execute(statement)
        return [self._to_domain(model) for model in result.scalars()]

    async def save(self, run: ValidationRun) -> ValidationRun:
        """保存当前记录。"""
        values = {
            "literature_run_id": run.literature_run_id,
            "attempt": run.attempt,
            "trace_id": run.trace_id,
            "status": run.status.value,
            "request": run.request.model_dump(mode="json"),
            "error": run.error,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
        }

        if run.id is None:
            model = ValidationRunModel(**values)
            self.session.add(model)
            await self.session.flush()
        else:
            model = await self.session.get(ValidationRunModel, run.id)
            if model is None:
                raise ValueError(f"ValidationRun {run.id} does not exist")
            for name, value in values.items():
                setattr(model, name, value)

        await self.session.execute(
            delete(ValidationRunReportModel).where(
                ValidationRunReportModel.validation_run_id == model.id
            )
        )
        self.session.add_all(
            [
                ValidationRunReportModel(
                    validation_run_id=model.id,
                    paper_id=report.paper_id,
                    position=position,
                    report=report.model_dump(mode="json"),
                )
                for position, report in enumerate(run.reports)
            ]
        )
        await self.session.flush()

        return run.model_copy(
            update={
                "id": model.id,
                "created_at": model.created_at,
            }
        )

    async def _get_one(
        self,
        *conditions: ColumnElement[bool],
    ) -> ValidationRun | None:
        statement = (
            select(ValidationRunModel)
            .options(selectinload(ValidationRunModel.reports))
            .where(*conditions)
        )
        result = await self.session.execute(statement)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    @staticmethod
    def _to_domain(model: ValidationRunModel) -> ValidationRun:
        return ValidationRun(
            id=model.id,
            literature_run_id=model.literature_run_id,
            attempt=model.attempt,
            trace_id=model.trace_id,
            status=ValidationRunStatus(model.status),
            request=ValidationRequest.model_validate(model.request),
            reports=[
                ValidationReport.model_validate(link.report)
                for link in model.reports
            ],
            error=model.error,
            created_at=model.created_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
        )


class TransactionalValidationRunRepository:
    """Persist every lifecycle transition in its own short transaction."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """初始化当前对象。"""
        self.session_factory = session_factory

    async def get_by_id(self, run_id: int) -> ValidationRun | None:
        """获取对应记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyValidationRunRepository(session)
            return await repository.get_by_id(run_id)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> ValidationRun | None:
        """获取对应记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyValidationRunRepository(session)
            return await repository.get_by_execution(
                literature_run_id,
                attempt,
            )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[ValidationRun]:
        """列出符合条件的记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyValidationRunRepository(session)
            return await repository.list_by_literature_run(
                literature_run_id
            )

    async def save(self, run: ValidationRun) -> ValidationRun:
        """保存当前记录。"""
        async with self.session_factory() as session:
            async with session.begin():
                repository = SqlAlchemyValidationRunRepository(session)
                return await repository.save(run)
