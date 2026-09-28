from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from module_agent.code.adapters.database.models.run import (
    CodeRunArtifactModel,
    CodeRunModel,
)
from module_agent.code.domain import (
    CodeAgentRequest,
    CodeArtifact,
    CodeRun,
    CodeRunStatus,
)


class SqlAlchemyCodeRunRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session

    async def get_by_id(self, run_id: int) -> CodeRun | None:
        """获取对应记录。"""
        return await self._get_one(CodeRunModel.id == run_id)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> CodeRun | None:
        """获取对应记录。"""
        return await self._get_one(
            CodeRunModel.literature_run_id == literature_run_id,
            CodeRunModel.attempt == attempt,
        )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[CodeRun]:
        """列出符合条件的记录。"""
        statement = (
            select(CodeRunModel)
            .options(selectinload(CodeRunModel.artifacts))
            .where(CodeRunModel.literature_run_id == literature_run_id)
            .order_by(CodeRunModel.attempt, CodeRunModel.id)
        )
        result = await self.session.execute(statement)
        return [self._to_domain(model) for model in result.scalars()]

    async def save(self, run: CodeRun) -> CodeRun:
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
            model = CodeRunModel(**values)
            self.session.add(model)
            await self.session.flush()
        else:
            model = await self.session.get(CodeRunModel, run.id)
            if model is None:
                raise ValueError(f"CodeRun {run.id} does not exist")
            for name, value in values.items():
                setattr(model, name, value)

        await self.session.execute(
            delete(CodeRunArtifactModel).where(
                CodeRunArtifactModel.code_run_id == model.id
            )
        )
        self.session.add_all(
            [
                CodeRunArtifactModel(
                    code_run_id=model.id,
                    paper_id=artifact.paper_id,
                    position=position,
                    artifact=artifact.model_dump(mode="json"),
                )
                for position, artifact in enumerate(run.artifacts)
            ]
        )
        await self.session.flush()

        return run.model_copy(
            update={
                "id": model.id,
                "created_at": model.created_at,
            }
        )

    async def _get_one(self, *conditions: object) -> CodeRun | None:
        statement = (
            select(CodeRunModel)
            .options(selectinload(CodeRunModel.artifacts))
            .where(*conditions)
        )
        result = await self.session.execute(statement)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    @staticmethod
    def _to_domain(model: CodeRunModel) -> CodeRun:
        return CodeRun(
            id=model.id,
            literature_run_id=model.literature_run_id,
            attempt=model.attempt,
            trace_id=model.trace_id,
            status=CodeRunStatus(model.status),
            request=CodeAgentRequest.model_validate(model.request),
            artifacts=[
                CodeArtifact.model_validate(link.artifact)
                for link in model.artifacts
            ],
            error=model.error,
            created_at=model.created_at,
            started_at=model.started_at,
            finished_at=model.finished_at,
        )


class TransactionalCodeRunRepository:
    """Persist every lifecycle transition in its own short transaction."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """初始化当前对象。"""
        self.session_factory = session_factory

    async def get_by_id(self, run_id: int) -> CodeRun | None:
        """获取对应记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyCodeRunRepository(session)
            return await repository.get_by_id(run_id)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> CodeRun | None:
        """获取对应记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyCodeRunRepository(session)
            return await repository.get_by_execution(
                literature_run_id,
                attempt,
            )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[CodeRun]:
        """列出符合条件的记录。"""
        async with self.session_factory() as session:
            repository = SqlAlchemyCodeRunRepository(session)
            return await repository.list_by_literature_run(
                literature_run_id
            )

    async def save(self, run: CodeRun) -> CodeRun:
        """保存当前记录。"""
        async with self.session_factory() as session:
            async with session.begin():
                repository = SqlAlchemyCodeRunRepository(session)
                return await repository.save(run)
