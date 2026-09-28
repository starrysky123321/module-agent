import asyncio
from contextlib import AsyncExitStack
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from module_agent.shared.config import app_settings


class PostgresCheckpointerManager:
    """管理外部客户端及其生命周期。"""
    def __init__(self, database_url: str):
        """初始化当前对象。"""
        self._database_url = database_url.strip()
        self._checkpointer: AsyncPostgresSaver | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
    
    async def start(self) -> AsyncPostgresSaver:
        """启动当前流程。"""
        if not self._database_url:
            raise RuntimeError("PostgresCheckpointerManager must be started with a database URL")
        if self._checkpointer is not None:
            return self._checkpointer
        
        async with self._lock:
            if self._checkpointer is not None:
                return self._checkpointer
            
            
            stack = AsyncExitStack()
            try:
                saver = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(
                        self._database_url
                    )
                )
            except Exception:
                await stack.aclose()
                raise
            
            self._checkpointer = saver
            self._exit_stack = stack
        
        return saver
        
    
    def get_checkpointer(self) -> AsyncPostgresSaver:
        """获取对应记录。"""
        if self._checkpointer is None:
            raise RuntimeError("PostgresCheckpointerManager must be started before using it")
        return self._checkpointer
        
    async def close(self) -> None:
        """关闭并释放外部资源。"""
        stack = self._exit_stack
        if stack is None:
            return

        try:
            await stack.aclose()
        finally:
            self._checkpointer = None
            self._exit_stack = None

        
postgres_checkpointer_manager = PostgresCheckpointerManager(app_settings.langgraph_database_url)
