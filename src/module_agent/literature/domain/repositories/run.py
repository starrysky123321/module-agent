from typing import Protocol

from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.run import LiteratureRun


class LiteratureRunRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get_by_id(self, run_id: int) -> LiteratureRun | None:
        """获取对应记录。"""
        ...

    async def save(self, run: LiteratureRun) -> LiteratureRun:
        """保存当前记录。"""
        ...

    async def replace_papers(
        self,
        run_id: int,
        papers: list[LiteratureRunPaper],
    ) -> None:
        """替换本次运行关联的论文列表。"""
        ...

    async def get_run_papers(self, run_id: int) -> list[LiteratureRunPaper]:
        """获取对应记录。"""
        ...
