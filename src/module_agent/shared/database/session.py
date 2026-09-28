from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from module_agent.shared.config import app_settings


def create_database_engine(database_url: str) -> AsyncEngine:
    """创建对应记录。"""
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return create_async_engine(
        database_url,
        pool_pre_ping=True,
    )


database_engine = create_database_engine(app_settings.database_url)

async_session_factory = async_sessionmaker(
    bind=database_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_database_session() -> AsyncIterator[AsyncSession]:
    """获取对应记录。"""
    async with async_session_factory() as session:
        async with session.begin():
            yield session
