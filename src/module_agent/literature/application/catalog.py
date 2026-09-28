from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.repositories.paper import PaperRepository


class PaperCatalogService:
    """封装相关应用用例。"""
    def __init__(self, repository: PaperRepository) -> None:
        """初始化当前对象。"""
        self.repository = repository

    async def upsert(self, paper: Paper) -> Paper:
        """新增记录或合并已有记录。"""
        existing: Paper | None = None
        if paper.doi and paper.doi.strip():
            existing = await self.repository.get_by_doi(paper.doi)

        if existing is None:
            existing = await self.repository.get_by_source(
                paper.source,
                paper.source_id,
            )

        if existing is None:
            return await self.repository.save(paper)

        return await self.repository.save(self._merge(existing, paper))

    @staticmethod
    def _merge(existing: Paper, incoming: Paper) -> Paper:
        return Paper(
            id=existing.id,
            source=existing.source,
            source_id=existing.source_id,
            title=incoming.title.strip() or existing.title,
            authors=incoming.authors or existing.authors,
            publication_year=(
                incoming.publication_year
                if incoming.publication_year is not None
                else existing.publication_year
            ),
            publication_date=incoming.publication_date or existing.publication_date,
            publication_type=(
                incoming.publication_type or existing.publication_type
            ),
            venue_id=(
                incoming.venue_id
                if incoming.venue_id is not None
                else existing.venue_id
            ),
            venue_name=incoming.venue_name or existing.venue_name,
            doi=incoming.doi or existing.doi,
            abstract=incoming.abstract or existing.abstract,
            landing_page_url=(
                incoming.landing_page_url or existing.landing_page_url
            ),
            pdf_url=incoming.pdf_url or existing.pdf_url,
            is_open_access=(
                existing.is_open_access or incoming.is_open_access
            ),
            open_access_status=(
                incoming.open_access_status or existing.open_access_status
            ),
            cited_by_count=max(
                existing.cited_by_count,
                incoming.cited_by_count,
            ),
            code_availability=existing.code_availability,
            code_repository_url=existing.code_repository_url,
            code_repository_confidence=existing.code_repository_confidence,
            code_repository_evidence=existing.code_repository_evidence,
        )
