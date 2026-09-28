from typing import Protocol

from module_agent.literature.domain.paper import Paper


class PaperRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get_by_source(
        self,
        source: str,
        source_id: str,
    ) -> Paper | None:
        """获取对应记录。"""
        ...

    async def get_by_doi(
        self,
        doi: str,
    ) -> Paper | None:
        """获取对应记录。"""
        ...

    async def save(
        self,
        paper: Paper,
    ) -> Paper:
        """保存当前记录。"""
        ...
        
    async def get_by_ids(
        self,
        paper_ids: list[int],
    ) -> list[Paper]:  
        """获取对应记录。"""
        ...
