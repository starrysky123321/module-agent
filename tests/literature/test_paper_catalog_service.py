import asyncio

from module_agent.literature.domain.paper import Paper
from module_agent.literature.application.catalog import PaperCatalogService


class FakePaperRepository:
    def __init__(
        self,
        *,
        by_doi: Paper | None = None,
        by_source: Paper | None = None,
    ) -> None:
        self.by_doi = by_doi
        self.by_source = by_source
        self.doi_queries: list[str] = []
        self.source_queries: list[tuple[str, str]] = []
        self.saved: list[Paper] = []

    async def get_by_doi(self, doi: str) -> Paper | None:
        self.doi_queries.append(doi)
        return self.by_doi

    async def get_by_source(self, source: str, source_id: str) -> Paper | None:
        self.source_queries.append((source, source_id))
        return self.by_source

    async def save(self, paper: Paper) -> Paper:
        self.saved.append(paper)
        if paper.id is None:
            return paper.model_copy(update={"id": 100})
        return paper


def paper(**updates: object) -> Paper:
    values: dict[str, object] = {
        "source": "openalex",
        "source_id": "W123",
        "title": "Example Paper",
        "authors": ["Author One"],
        "doi": "10.1000/example",
        "cited_by_count": 10,
    }
    values.update(updates)
    return Paper.model_validate(values)


def test_paper_catalog_creates_unknown_paper() -> None:
    repository = FakePaperRepository()
    service = PaperCatalogService(repository)

    saved = asyncio.run(service.upsert(paper()))

    assert saved.id == 100
    assert repository.doi_queries == ["10.1000/example"]
    assert repository.source_queries == [("openalex", "W123")]
    assert len(repository.saved) == 1


def test_paper_catalog_updates_paper_found_by_doi() -> None:
    existing = paper(
        id=7,
        source="openalex",
        source_id="W-old",
        title="Old Title",
        authors=["Old Author"],
        abstract="Existing abstract",
        pdf_url=None,
        is_open_access=False,
        cited_by_count=20,
    )
    incoming = paper(
        source="semantic-scholar",
        source_id="S-new",
        title="Updated Title",
        authors=[],
        abstract=None,
        pdf_url="https://example.com/paper.pdf",
        is_open_access=True,
        cited_by_count=15,
    )
    repository = FakePaperRepository(by_doi=existing)
    service = PaperCatalogService(repository)

    saved = asyncio.run(service.upsert(incoming))

    assert repository.source_queries == []
    assert saved.id == 7
    assert saved.source == "openalex"
    assert saved.source_id == "W-old"
    assert saved.title == "Updated Title"
    assert saved.authors == ["Old Author"]
    assert saved.abstract == "Existing abstract"
    assert saved.pdf_url == "https://example.com/paper.pdf"
    assert saved.is_open_access is True
    assert saved.cited_by_count == 20


def test_paper_catalog_uses_source_identity_without_doi() -> None:
    existing = paper(id=8, doi=None)
    incoming = paper(doi=None, title="Refreshed Title")
    repository = FakePaperRepository(by_source=existing)
    service = PaperCatalogService(repository)

    saved = asyncio.run(service.upsert(incoming))

    assert repository.doi_queries == []
    assert repository.source_queries == [("openalex", "W123")]
    assert saved.id == 8
    assert saved.title == "Refreshed Title"
