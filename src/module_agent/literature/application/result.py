from module_agent.literature.domain.repositories.paper import PaperRepository
from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.shared.exceptions import LiteratureRunNotFoundError

class LiteratureResultService:
    """封装相关应用用例。"""
    def __init__(
        self,
        paper_repository: PaperRepository,
        run_repository: LiteratureRunRepository,
    ) -> None:
        """初始化当前对象。"""
        self.paper_repository = paper_repository
        self.run_repository = run_repository
            
            
    async def get_papers(
        self,
        run_id: int,
    ) -> list[LiteraturePaperRecommendation]:
        """获取对应记录。"""
        run = await self.run_repository.get_by_id(run_id)
        if run is None:
            raise LiteratureRunNotFoundError(run_id)
        run_papers = await self.run_repository.get_run_papers(run_id)
        papers = await self.paper_repository.get_by_ids(
            [run_paper.paper_id for run_paper in run_papers]
        )
        papers_by_id = {
            paper.id: paper
            for paper in papers
            if paper.id is not None
        }

        return [
            LiteraturePaperRecommendation(
                **papers_by_id[run_paper.paper_id].model_dump(),
                position=run_paper.position,
                relevance_score=run_paper.relevance_score,
                relevance_reason=run_paper.relevance_reason,
                matched_terms=run_paper.matched_terms,
                method_profile=run_paper.method_profile,
            )
            for run_paper in run_papers
            if run_paper.paper_id in papers_by_id
        ]
