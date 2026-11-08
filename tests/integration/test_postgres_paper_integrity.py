"""Persist evidence in rollback-only fixture rows; never touch user records."""

import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from module_agent.bootstrap import database_models  # noqa: F401
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.literature.adapters.database.models.run import LiteratureRunModel
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)
from module_agent.literature.domain.integrity import (
    PaperIntegrity,
    PaperIntegrityStatus,
)
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.shared.config import app_settings
from module_agent.shared.database.session import create_database_engine

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="Opt-in PostgreSQL fixture test",
)


def test_integrity_roundtrip_and_historical_null_stay_distinct():
    async def verify():
        engine = create_database_engine(app_settings.database_url)
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                factory = async_sessionmaker(
                    bind=connection,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                try:
                    async with factory() as session, session.begin():
                        run = LiteratureRunModel(status="completed", request={})
                        paper = PaperModel(
                            source="integrity-test",
                            source_id=str(uuid4()),
                            title="Rollback-only integrity fixture",
                        )
                        legacy = PaperModel(
                            source="integrity-test",
                            source_id=str(uuid4()),
                            title="Rollback-only historical fixture",
                        )
                        session.add_all([run, paper, legacy])
                        await session.flush()
                        run_id, paper_id, legacy_id = run.id, paper.id, legacy.id
                        fact = PaperIntegrity(
                            status=PaperIntegrityStatus.RETRACTED,
                            sources=["crossref"],
                            evidence=["Retracted: fixture"],
                        )
                        await SqlAlchemyLiteratureRunRepository(session).replace_papers(
                            run_id,
                            [
                                LiteratureRunPaper(
                                    paper_id=paper_id, position=0, integrity=fact
                                ),
                                LiteratureRunPaper(paper_id=legacy_id, position=1),
                            ],
                        )
                    async with factory() as session:
                        restored = await SqlAlchemyLiteratureRunRepository(
                            session
                        ).get_run_papers(run_id)
                        assert restored[0].integrity == fact
                        assert restored[1].integrity is None
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    asyncio.run(verify())
