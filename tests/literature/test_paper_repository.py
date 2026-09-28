import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.paper import Paper
from module_agent.literature.adapters.database.models.paper import PaperModel
from module_agent.literature.adapters.database.repositories.paper import (
    SqlAlchemyPaperRepository,
)


def example_paper(**updates: object) -> Paper:
    values: dict[str, object] = {
        "source": " OpenAlex ",
        "source_id": "W123",
        "title": "Example Paper",
        "authors": ["Example Author"],
        "doi": " 10.1000/EXAMPLE ",
        "is_open_access": True,
        "cited_by_count": 7,
    }
    values.update(updates)
    return Paper.model_validate(values)


def test_paper_repository_get_by_source_maps_domain_entity() -> None:
    model = PaperModel(
        id=1,
        source="openalex",
        source_id="W123",
        title="Example Paper",
        authors=["Example Author"],
        doi="10.1000/example",
        is_open_access=True,
        cited_by_count=7,
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyPaperRepository(session)

    paper = asyncio.run(repository.get_by_source(" OpenAlex ", " W123 "))

    assert paper is not None
    assert paper.id == 1
    assert paper.source == "openalex"
    assert paper.authors == ["Example Author"]
    statement = session.execute.await_args.args[0]
    assert "openalex" in statement.compile().params.values()
    assert "W123" in statement.compile().params.values()


def test_paper_repository_get_by_ids_preserves_requested_order() -> None:
    first_model = PaperModel(
        id=10,
        source="openalex",
        source_id="W10",
        title="First Paper",
        authors=[],
        is_open_access=False,
        cited_by_count=0,
    )
    second_model = PaperModel(
        id=20,
        source="openalex",
        source_id="W20",
        title="Second Paper",
        authors=[],
        is_open_access=False,
        cited_by_count=0,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [first_model, second_model]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyPaperRepository(session)

    papers = asyncio.run(repository.get_by_ids([20, 999, 10]))

    assert [paper.id for paper in papers] == [20, 10]
    session.execute.assert_awaited_once()
    statement = session.execute.await_args.args[0]
    assert set(statement.compile().params["id_1"]) == {10, 20, 999}


def test_paper_repository_get_by_ids_skips_query_for_empty_input() -> None:
    session = AsyncMock(spec=AsyncSession)
    repository = SqlAlchemyPaperRepository(session)

    papers = asyncio.run(repository.get_by_ids([]))

    assert papers == []
    session.execute.assert_not_awaited()


def test_paper_repository_saves_new_paper_without_commit() -> None:
    session = AsyncMock(spec=AsyncSession)

    def assign_id(model: PaperModel) -> None:
        model.id = 10

    session.add.side_effect = assign_id
    repository = SqlAlchemyPaperRepository(session)

    saved = asyncio.run(repository.save(example_paper()))

    model = session.add.call_args.args[0]
    assert isinstance(model, PaperModel)
    assert saved.id == 10
    assert saved.source == "openalex"
    assert saved.source_id == "W123"
    assert saved.doi == "10.1000/example"
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_paper_repository_updates_existing_paper() -> None:
    model = PaperModel(
        id=5,
        source="openalex",
        source_id="W123",
        title="Old Title",
        authors=[],
        is_open_access=False,
        cited_by_count=0,
    )
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = model
    repository = SqlAlchemyPaperRepository(session)
    paper = example_paper(id=5, title="Updated Title", cited_by_count=20)

    saved = asyncio.run(repository.save(paper))

    session.get.assert_awaited_once_with(PaperModel, 5)
    assert model.title == "Updated Title"
    assert model.cited_by_count == 20
    assert saved.id == 5
    session.flush.assert_awaited_once_with()
    session.commit.assert_not_awaited()


def test_paper_repository_maps_code_availability_fields() -> None:
    model = PaperModel(
        id=8,
        source="openalex",
        source_id="W8",
        title="Paper with Code",
        authors=[],
        is_open_access=False,
        cited_by_count=0,
        code_availability="open_source",
        code_repository_url="https://github.com/alice/code",
        code_repository_confidence=0.95,
        code_repository_evidence=[{"evidence_type": "paper_url"}],
    )
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result

    paper = asyncio.run(
        SqlAlchemyPaperRepository(session).get_by_source("openalex", "W8")
    )

    assert paper is not None
    assert paper.code_availability == "open_source"
    assert paper.code_repository_url == "https://github.com/alice/code"
    assert paper.code_repository_confidence == 0.95
    assert paper.code_repository_evidence == [
        {"evidence_type": "paper_url"}
    ]
