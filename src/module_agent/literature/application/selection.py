from module_agent.literature.domain.repositories.run import LiteratureRunRepository
from module_agent.workflow.domain import PaperSelectionRequest
from module_agent.shared.exceptions import LiteratureRunNotFoundError, LiteratureRunStateError
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.domain.repositories.selection import PaperSelectionRepository
from module_agent.literature.domain.selection import PaperSelection
from module_agent.shared.exceptions import PaperSelectionAlreadyExistsError, InvalidPaperSelectionError


class PaperSelectionService:
    """封装相关应用用例。"""
    def __init__(self, literature_run_repository: LiteratureRunRepository,
                 paper_selection_repository: PaperSelectionRepository):
        """初始化当前对象。"""
        self.literature_run_repository = literature_run_repository
        self.paper_selection_repository = paper_selection_repository

    async def confirm_selection(
        self,
        run_id: int,
        request: PaperSelectionRequest,
    ) -> PaperSelection:
        """校验并保存用户选择的论文。"""
        literature_run = await self.literature_run_repository.get_by_id(run_id)
        request_papers_ids = request.selected_paper_ids
        
        if not literature_run:
            raise LiteratureRunNotFoundError(run_id)
        
        if literature_run.status != LiteratureRunStatus.COMPLETED:
            raise LiteratureRunStateError(run_id, "select papers")

        paper_selection = await self.paper_selection_repository.get_by_run_id(run_id)
        if paper_selection is not None:
            raise PaperSelectionAlreadyExistsError(run_id)
        papers = await self.literature_run_repository.get_run_papers(run_id)
        task_papers_ids = [paper.paper_id for paper in papers]

        invalid_paper_ids = [
            paper_id
            for paper_id in request_papers_ids
            if paper_id not in task_papers_ids
        ]
        if invalid_paper_ids:
            raise InvalidPaperSelectionError(run_id, invalid_paper_ids)
        
        selection = PaperSelection(
            run_id=run_id,
            selected_paper_ids=request_papers_ids,
            code_requirements=request.code_requirements,
        )
        
        return await self.paper_selection_repository.create(selection)
            
            
