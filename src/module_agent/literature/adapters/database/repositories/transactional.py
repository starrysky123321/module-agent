"""Short transactions for workflow access; never hold a session across graph I/O."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.literature.adapters.database.repositories.paper import (
    SqlAlchemyPaperRepository,
)
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)
from module_agent.literature.adapters.database.repositories.selection import (
    SqlAlchemyPaperSelectionRepository,
)
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.run import LiteratureRun
from module_agent.literature.domain.selection import PaperSelection


class TransactionalLiteratureRunRepository:
    """Release the connection before dispatching or resuming a workflow."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_id(self, run_id: int) -> LiteratureRun | None:
        async with self.session_factory() as session:
            return await SqlAlchemyLiteratureRunRepository(session).get_by_id(run_id)

    async def save(self, run: LiteratureRun) -> LiteratureRun:
        async with self.session_factory() as session, session.begin():
            return await SqlAlchemyLiteratureRunRepository(session).save(run)

    async def get_run_papers(self, run_id: int) -> list[LiteratureRunPaper]:
        async with self.session_factory() as session:
            return await SqlAlchemyLiteratureRunRepository(session).get_run_papers(
                run_id
            )

    async def replace_papers(
        self, run_id: int, papers: list[LiteratureRunPaper]
    ) -> None:
        async with self.session_factory() as session, session.begin():
            await SqlAlchemyLiteratureRunRepository(session).replace_papers(
                run_id, papers
            )


class TransactionalPaperSelectionRepository:
    """Commit selection before the graph can publish downstream jobs."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_run_id(self, run_id: int) -> PaperSelection | None:
        async with self.session_factory() as session:
            return await SqlAlchemyPaperSelectionRepository(session).get_by_run_id(
                run_id
            )

    async def create(self, selection: PaperSelection) -> PaperSelection:
        async with self.session_factory() as session, session.begin():
            return await SqlAlchemyPaperSelectionRepository(session).create(selection)


class TransactionalPaperRepository:
    """Load detached domain objects without retaining a workflow connection."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.session_factory = session_factory

    async def get_by_ids(self, paper_ids: list[int]) -> list[Paper]:
        async with self.session_factory() as session:
            return await SqlAlchemyPaperRepository(session).get_by_ids(paper_ids)

    async def get_by_source(self, source: str, source_id: str) -> Paper | None:
        async with self.session_factory() as session:
            return await SqlAlchemyPaperRepository(session).get_by_source(
                source, source_id
            )

    async def get_by_doi(self, doi: str) -> Paper | None:
        async with self.session_factory() as session:
            return await SqlAlchemyPaperRepository(session).get_by_doi(doi)

    async def save(self, paper: Paper) -> Paper:
        async with self.session_factory() as session, session.begin():
            return await SqlAlchemyPaperRepository(session).save(paper)
