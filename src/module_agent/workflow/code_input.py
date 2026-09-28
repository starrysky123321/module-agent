from module_agent.code.domain.request import CodePaperInput
from module_agent.literature.domain.repositories.paper import (
    PaperRepository,
)
from module_agent.literature.domain.repositories.run import (
    LiteratureRunRepository,
)


class SelectedPaperCodeInputLoader:
    """把用户选中的持久化论文转换成 Code Agent 输入。"""

    def __init__(
        self,
        *,
        paper_repository: PaperRepository,
        literature_run_repository: LiteratureRunRepository,
    ) -> None:
        """注入论文和 LiteratureRun 仓库。"""
        self.paper_repository = paper_repository
        self.literature_run_repository = literature_run_repository
    
    async def load(
        self,
        literature_run_id: int,
        selected_paper_ids: list[int],
    ) -> list[CodePaperInput]:
        """按用户选择顺序加载论文及其本次运行的方法画像。"""
        run_papers = await self.literature_run_repository.get_run_papers(
            literature_run_id,
        )
        
        papers = await self.paper_repository.get_by_ids(selected_paper_ids)
        
        run_paper_by_id = {
            item.paper_id: item
            for item in run_papers
        }
        
        paper_by_id = {
            paper.id: paper
            for paper in papers
            if paper.id is not None
        }
        
        missing_ids = [
            paper_id
            for paper_id in selected_paper_ids
            if paper_id not in paper_by_id
        ]
        
        if missing_ids:
            raise ValueError(f"missing paper ids: {missing_ids}")
        
        result: list[CodePaperInput] = []
        
        for paper_id in selected_paper_ids:
            paper = paper_by_id[paper_id]
            run_paper = run_paper_by_id.get(paper_id)

            result.append(
                CodePaperInput(
                    paper_id=paper_id,
                    source=paper.source,
                    source_id=paper.source_id,
                    title=paper.title,
                    authors=paper.authors,
                    doi=paper.doi,
                    abstract=paper.abstract,
                    landing_page_url=paper.landing_page_url,
                    method_profile=(
                        run_paper.method_profile
                        if run_paper is not None
                        else None
                    ),
                    pdf_url=paper.pdf_url,
                )
            )
        
        return result
