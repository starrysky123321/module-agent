from typing import Protocol
from module_agent.literature.domain.selection import PaperSelection


class PaperSelectionRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get_by_run_id(self, run_id: int) -> PaperSelection | None:
        """获取对应记录。"""
        ...
        
    async def create(self, selection: PaperSelection) -> PaperSelection:
        """创建并保存对应记录。"""
        ...
