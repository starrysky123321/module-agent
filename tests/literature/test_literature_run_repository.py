import asyncio
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.llm_metric import LlmCallMetric, LlmCallOutcome
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.adapters.database.models.run import (
    LiteratureRunModel,
    LiteratureRunPaperModel,
)
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)


def example_request() -> SearchRequest:
    return SearchRequest(
        topic="graph neural networks",
        description="Find representative papers",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["GNN"],
        max_results=10,
    )


def test_literature_run_repository_saves_new_run_without_commit() -> None:
    metric = LlmCallMetric(
        stage="query_planning",
        model="test-qwen",
        item_count=1,
        duration_ms=25.0,
        timeout_seconds=180.0,
        outcome=LlmCallOutcome.SUCCESS,
    )
    session = AsyncMock(spec=AsyncSession)

    def assign_generated_values(model: LiteratureRunModel) -> None:
        model.id = 12
        model.created_at = datetime(2026, 8, 27, tzinfo=timezone.utc)

    session.add.side_effect = assign_generated_values
    repository = SqlAlchemyLiteratureRunRepository(session)

    saved = asyncio.run(
        repository.save(
            LiteratureRun(request=example_request(), llm_metrics=[metric])
        )
    )

    model = session.add.call_args.args[0]
    assert isinstance(model, LiteratureRunModel)
    assert model.request["start_date"] == "2024-01-01"
    assert model.llm_metrics == [metric.model_dump(mode="json")]
    assert saved.id == 12
    assert saved.status is LiteratureRunStatus.PENDING
    assert saved.llm_metrics == [metric]
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_literature_run_repository_replaces_ordered_paper_links() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = LiteratureRunModel(
        id=3,
        status=LiteratureRunStatus.RUNNING,
        request=example_request().model_dump(mode="json"),
    )
    repository = SqlAlchemyLiteratureRunRepository(session)

    run_papers = [
        LiteratureRunPaper(
            paper_id=20,
            position=0,
            relevance_score=0.9,
            relevance_reason="Direct match",
            matched_terms=["graph", "oversmoothing"],
        ),
        LiteratureRunPaper(
            paper_id=10,
            position=1,
            relevance_score=0.7,
            relevance_reason="Partial match",
            matched_terms=["graph"],
        ),
    ]

    asyncio.run(repository.replace_papers(3, run_papers))

    links = session.add_all.call_args.args[0]
    assert [type(link) for link in links] == [
        LiteratureRunPaperModel,
        LiteratureRunPaperModel,
    ]
    assert [(link.paper_id, link.position) for link in links] == [(20, 0), (10, 1)]
    assert links[0].relevance_score == 0.9
    assert links[0].relevance_reason == "Direct match"
    assert links[0].matched_terms == ["graph", "oversmoothing"]
    session.execute.assert_awaited_once()
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_literature_run_repository_reads_run_papers_in_query_order() -> None:
    scalar_result = MagicMock()
    scalar_result.all.return_value = [
        LiteratureRunPaperModel(
            run_id=3,
            paper_id=20,
            position=0,
            relevance_score=0.9,
            relevance_reason="Direct match",
            matched_terms=["graph"],
        ),
        LiteratureRunPaperModel(
            run_id=3,
            paper_id=10,
            position=1,
            relevance_score=0.7,
            relevance_reason="Partial match",
            matched_terms=[],
        ),
    ]
    result = MagicMock()
    result.scalars.return_value = scalar_result
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyLiteratureRunRepository(session)

    run_papers = asyncio.run(repository.get_run_papers(3))

    assert [paper.paper_id for paper in run_papers] == [20, 10]
    assert [paper.relevance_score for paper in run_papers] == [0.9, 0.7]
