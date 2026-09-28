from typing import Protocol
from module_agent.venue_catalog.domain.models import Venue


class VenueCache(Protocol):
    """提供缓存访问能力。"""
    async def get(self, name: str) -> Venue | None:
        """从缓存读取会议期刊。"""
        ...

    async def set(self, name: str, venue: Venue) -> None:
        """把会议期刊写入缓存。"""
        ...

    async def delete(self, name: str) -> None:
        """删除对应记录。"""
        ...
        
    async def clear(self) -> None:
        """清空所有会议期刊缓存。"""
        ...
