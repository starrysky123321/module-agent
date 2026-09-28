from typing import Protocol

from module_agent.venue_catalog.domain.models import Venue


class VenueRepository(Protocol):
    """提供数据持久化访问能力。"""
    async def get_by_name(self, name: str) -> Venue | None:
        """获取对应记录。"""
        ...
        
