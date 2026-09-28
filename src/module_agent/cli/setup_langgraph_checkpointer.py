import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.shared.config import app_settings


async def setup_checkpointer() -> None:
    """初始化所需资源。"""
    url = app_settings.langgraph_database_url.strip()
    
    if url == "":
        raise RuntimeError("langgraph_database_url is empty")
    
    async with AsyncPostgresSaver.from_conn_string(url) as checkpointer:
        await checkpointer.setup()


def main() -> None:
    """运行命令行入口。"""
    asyncio.run(setup_checkpointer())

if __name__ == "__main__":
    main()
