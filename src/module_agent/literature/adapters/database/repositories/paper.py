from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.paper import Paper
from module_agent.literature.adapters.database.models.paper import PaperModel


class SqlAlchemyPaperRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session
        
        
    async def get_by_ids(
        self,
        paper_ids: list[int],
    ) -> list[Paper]:
        """获取对应记录。"""
        if not paper_ids:
            return []

        statement = select(PaperModel).where(
            PaperModel.id.in_(paper_ids)
        )

        result = await self.session.execute(statement)
        models = result.scalars().all()

        models_by_id = {
            model.id: model
            for model in models
        }

        return [
            self._to_domain(models_by_id[paper_id])
            for paper_id in paper_ids
            if paper_id in models_by_id
        ]

    async def get_by_source(
        self,
        source: str,
        source_id: str,
    ) -> Paper | None:
        """获取对应记录。"""
        normalized_source = source.strip().casefold()
        normalized_source_id = source_id.strip()
        if not normalized_source or not normalized_source_id:
            return None

        statement = select(PaperModel).where(
            PaperModel.source == normalized_source,
            PaperModel.source_id == normalized_source_id,
        )
        result = await self.session.execute(statement)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    async def get_by_doi(self, doi: str) -> Paper | None:
        """获取对应记录。"""
        normalized_doi = self._normalize_doi(doi)
        if normalized_doi is None:
            return None

        statement = select(PaperModel).where(PaperModel.doi == normalized_doi)
        result = await self.session.execute(statement)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model is not None else None

    async def save(self, paper: Paper) -> Paper:
        """保存当前记录。"""
        values = self._persistence_values(paper)

        if paper.id is None:
            model = PaperModel(**values)
            self.session.add(model)
        else:
            model = await self.session.get(PaperModel, paper.id)
            if model is None:
                raise ValueError(f"Paper with id {paper.id} does not exist")
            for field_name, value in values.items():
                setattr(model, field_name, value)

        await self.session.flush()
        return self._to_domain(model)

    @classmethod
    def _persistence_values(cls, paper: Paper) -> dict[str, object]:
        normalized_source = paper.source.strip().casefold()
        normalized_source_id = paper.source_id.strip()
        if not normalized_source:
            raise ValueError("Paper source cannot be empty")
        if not normalized_source_id:
            raise ValueError("Paper source_id cannot be empty")

        return {
            "source": normalized_source,
            "source_id": normalized_source_id,
            "title": paper.title,
            "authors": list(paper.authors),
            "publication_year": paper.publication_year,
            "publication_date": paper.publication_date,
            "publication_type": paper.publication_type,
            "venue_id": paper.venue_id,
            "venue_name": paper.venue_name,
            "doi": cls._normalize_doi(paper.doi),
            "abstract": paper.abstract,
            "landing_page_url": paper.landing_page_url,
            "pdf_url": paper.pdf_url,
            "is_open_access": paper.is_open_access,
            "open_access_status": paper.open_access_status,
            "cited_by_count": paper.cited_by_count,
            "code_availability": paper.code_availability,
            "code_repository_url": paper.code_repository_url,
            "code_repository_confidence": paper.code_repository_confidence,
            "code_repository_evidence": list(
                paper.code_repository_evidence
            ),
        }

    @staticmethod
    def _normalize_doi(doi: str | None) -> str | None:
        if doi is None:
            return None
        normalized_doi = doi.strip().casefold()
        return normalized_doi or None

    @staticmethod
    def _to_domain(model: PaperModel) -> Paper:
        return Paper(
            id=model.id,
            source=model.source,
            source_id=model.source_id,
            title=model.title,
            authors=list(model.authors),
            publication_year=model.publication_year,
            publication_date=model.publication_date,
            publication_type=model.publication_type,
            venue_id=model.venue_id,
            venue_name=model.venue_name,
            doi=model.doi,
            abstract=model.abstract,
            landing_page_url=model.landing_page_url,
            pdf_url=model.pdf_url,
            is_open_access=model.is_open_access,
            open_access_status=model.open_access_status,
            cited_by_count=model.cited_by_count,
            code_availability=model.code_availability or "unknown",
            code_repository_url=model.code_repository_url,
            code_repository_confidence=model.code_repository_confidence,
            code_repository_evidence=list(
                model.code_repository_evidence or []
            ),
        )
