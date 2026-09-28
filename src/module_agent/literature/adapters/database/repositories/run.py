from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.domain.search import SearchRequest
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.run import LiteratureRun
from module_agent.literature.adapters.database.models.run import (
    LiteratureRunModel,
    LiteratureRunPaperModel,
)
from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.search import SourceSearchMetric
from module_agent.literature.domain.llm_metric import LlmCallMetric


class SqlAlchemyLiteratureRunRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session

    async def get_by_id(self, run_id: int) -> LiteratureRun | None:
        """获取对应记录。"""
        model = await self.session.get(LiteratureRunModel, run_id)
        return self._to_domain(model) if model is not None else None

    async def save(self, run: LiteratureRun) -> LiteratureRun:
        """保存当前记录。"""
        values = self._persistence_values(run)

        if run.id is None:
            if run.created_at is not None:
                values["created_at"] = run.created_at
            model = LiteratureRunModel(**values)
            self.session.add(model)
        else:
            model = await self.session.get(LiteratureRunModel, run.id)
            if model is None:
                raise ValueError(f"Literature run with id {run.id} does not exist")
            for field_name, value in values.items():
                setattr(model, field_name, value)

        await self.session.flush()
        return self._to_domain(model)

    async def replace_papers(
        self,
        run_id: int,
        papers: list[LiteratureRunPaper],
    ) -> None:
        """替换本次运行关联的论文列表。"""
        if await self.session.get(LiteratureRunModel, run_id) is None:
            raise ValueError(f"Literature run with id {run_id} does not exist")
        paper_ids = [paper.paper_id for paper in papers]
        positions = [paper.position for paper in papers]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("A literature run cannot contain duplicate paper ids")
        if len(positions) != len(set(positions)):
            raise ValueError("A literature run cannot contain duplicate positions")

        await self.session.execute(
            delete(LiteratureRunPaperModel).where(
                LiteratureRunPaperModel.run_id == run_id,
            )
        )
        self.session.add_all(
            [
                LiteratureRunPaperModel(
                    run_id=run_id,
                    paper_id=paper.paper_id,
                    position=paper.position,
                    relevance_score=paper.relevance_score,
                    relevance_reason=paper.relevance_reason,
                    matched_terms=list(paper.matched_terms),
                    method_profile=paper.method_profile.model_dump(mode="json") if paper.method_profile is not None else None,
                )
                for paper in papers
            ]
        )
        await self.session.flush()

    async def get_run_papers(self, run_id: int) -> list[LiteratureRunPaper]:
        """获取对应记录。"""
        statement = (
            select(LiteratureRunPaperModel)
            .where(LiteratureRunPaperModel.run_id == run_id)
            .order_by(LiteratureRunPaperModel.position)
        )
        result = await self.session.execute(statement)
        return [
            LiteratureRunPaper(
                paper_id=model.paper_id,
                position=model.position,
                relevance_score=model.relevance_score,
                relevance_reason=model.relevance_reason,
                matched_terms=list(model.matched_terms),
                method_profile=PaperMethodProfile.model_validate(model.method_profile) if model.method_profile is not None else None,
            )
            for model in result.scalars().all()
        ]

    @staticmethod
    def _persistence_values(run: LiteratureRun) -> dict[str, object]:
        return {
            "status": run.status,
            "request": run.request.model_dump(mode="json"),
            "search_queries": list(run.search_queries),
            "warnings": list(run.warnings),
            "source_metrics": [
                metric.model_dump(mode="json")
                for metric in run.source_metrics
            ],
            "llm_metrics": [
                metric.model_dump(mode="json")
                for metric in run.llm_metrics
            ],
            "error": run.error,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
        }

    @staticmethod
    def _to_domain(model: LiteratureRunModel) -> LiteratureRun:
        return LiteratureRun(
            id=model.id,
            status=model.status,
            request=SearchRequest.model_validate(model.request),
            search_queries=list(model.search_queries),
            warnings=list(model.warnings),
            source_metrics=[
                SourceSearchMetric.model_validate(metric)
                for metric in model.source_metrics
            ],
            llm_metrics=[
                LlmCallMetric.model_validate(metric)
                for metric in model.llm_metrics
            ],
            error=model.error,
            created_at=model.created_at,
            started_at=model.started_at,
            completed_at=model.completed_at,
        )
