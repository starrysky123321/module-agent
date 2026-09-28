from sqlalchemy.ext.asyncio import AsyncSession
from module_agent.literature.adapters.database.models.selection import PaperSelectionModel
from module_agent.literature.domain.selection import PaperSelection
import sqlalchemy.exc
from module_agent.shared.exceptions import PaperSelectionAlreadyExistsError



class SqlAlchemyPaperSelectionRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession):
        """初始化当前对象。"""
        self.session = session
        
    async def get_by_run_id(self, run_id: int) -> PaperSelection | None:
        """获取对应记录。"""
        model = await self.session.get(PaperSelectionModel, run_id)
        return self._to_domain(model) if model is not None else None
    
    async def create(self, selection: PaperSelection) -> PaperSelection:
        
        """创建并保存对应记录。"""
        values: dict[str, object] = {
            "run_id": selection.run_id,
            "selected_paper_ids": list(selection.selected_paper_ids),
            "code_requirements": selection.code_requirements,
        }
        if selection.selected_at is not None:
            values["selected_at"] = selection.selected_at
        
        result = PaperSelectionModel(**values)
        
        self.session.add(result)
        
        try:
            await self.session.flush()
        except sqlalchemy.exc.IntegrityError as exc:
            raise PaperSelectionAlreadyExistsError(selection.run_id) from exc
        
        await self.session.refresh(result)   
        return self._to_domain(result)
        

    @staticmethod
    def _to_domain(model: PaperSelectionModel) -> PaperSelection:
        return PaperSelection(
            run_id=model.run_id,
            selected_paper_ids=list(model.selected_paper_ids),
            code_requirements=model.code_requirements,
            selected_at=model.selected_at,
        )
