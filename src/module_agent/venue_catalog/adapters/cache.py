import logging

from pydantic import TypeAdapter, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError

from module_agent.venue_catalog.domain.models import Venue


logger = logging.getLogger(__name__)

_venue_adapter: TypeAdapter[Venue] = TypeAdapter(Venue)

_KEY_PREFIX = "venue:v1:"


class RedisVenueCache:
    """提供缓存访问能力。"""
    def __init__(
        self,
        client: Redis,
        ttl_seconds: int = 86400,
    ) -> None:
        """初始化当前对象。"""
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds必须大于0")

        self._client = client
        self._ttl_seconds = ttl_seconds

    async def get(
        self,
        name: str,
    ) -> Venue | None:
        """从缓存读取会议期刊。"""
        key = self._build_key(name)

        try:
            cached_data = await self._client.get(key)
        except RedisError:
            # Redis异常时降级为缓存未命中，继续查数据库
            logger.warning(
                "读取Venue缓存失败",
                exc_info=True,
            )
            return None

        if cached_data is None:
            return None

        try:
            return _venue_adapter.validate_json(cached_data)
        except ValidationError:
            # 缓存数据已经过期或结构不兼容，删除坏数据
            logger.warning(
                "Venue缓存数据解析失败，删除缓存",
                exc_info=True,
            )

            try:
                await self._client.delete(key)
            except RedisError:
                logger.warning(
                    "删除损坏的Venue缓存失败",
                    exc_info=True,
                )

            return None

    async def set(
        self,
        name: str,
        venue: Venue,
    ) -> None:
        """把会议期刊写入缓存。"""
        key = self._build_key(name)
        cached_data = _venue_adapter.dump_json(venue)

        try:
            await self._client.set(
                key,
                cached_data,
                ex=self._ttl_seconds,
            )
        except RedisError:
            # 写缓存失败不能影响正常业务
            logger.warning(
                "写入Venue缓存失败",
                exc_info=True,
            )

    async def delete(
        self,
        name: str,
    ) -> None:
        """删除对应记录。"""
        key = self._build_key(name)

        try:
            await self._client.delete(key)
        except RedisError:
            logger.warning(
                "删除Venue缓存失败",
                exc_info=True,
            )
            
            
    async def clear(self) -> None:
        """清空所有会议期刊缓存。"""
        keys: list[str] = []
        try:
            async for key in self._client.scan_iter(
                match=f"{_KEY_PREFIX}*",
                count=100,
            ):
                keys.append(key)
                
                if len(keys) >= 100:
                    try:
                        await self._client.delete(*keys)
                    except RedisError:
                        logger.warning(
                            "删除Venue缓存失败",
                            exc_info=True,
                        )
                    keys.clear()
            
            if keys:
                try:
                    await self._client.delete(*keys)
                except RedisError:
                    logger.warning(
                        "删除Venue缓存失败",
                        exc_info=True,
                    )
                    keys.clear()
        except RedisError:
            logger.warning(
                "删除Venue缓存失败",
                exc_info=True,
            )
            
        

    @staticmethod
    def _build_key(name: str) -> str:
        normalized_name = " ".join(
            name.casefold().split()
        )

        return f"{_KEY_PREFIX}{normalized_name}"
