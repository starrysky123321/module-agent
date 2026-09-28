import asyncio
from dataclasses import asdict

from module_agent.shared.cache.redis import redis_client
from module_agent.venue_catalog.adapters.cache import RedisVenueCache
from module_agent.shared.database import (
    async_session_factory,
    database_engine,
)
from module_agent.venue_catalog.adapters.database.importer import (
    import_icore_catalog,
)
from module_agent.venue_catalog.adapters.rankings.icore import download_icore_catalog


async def import_catalog() -> None:
    """导入外部数据。"""
    try:
        records = download_icore_catalog()

        async with async_session_factory() as session:
            async with session.begin():
                stats = await import_icore_catalog(session, records)

        await RedisVenueCache(redis_client).clear()
        print(asdict(stats))
    finally:
        try:
            await redis_client.aclose()
        finally:
            await database_engine.dispose()


def main() -> None:
    """运行命令行入口。"""
    asyncio.run(import_catalog())


if __name__ == "__main__":
    main()
