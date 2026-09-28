from typing import Protocol

from collections.abc import Awaitable, Callable

from pydantic import BaseModel, Field
from uuid import UUID

class LiteratureJobQueue(Protocol):
    """封装 LiteratureJobQueue 相关的数据和行为。"""
    async def enqueue(
        self,
        run_id: int,
        resume_workflow: bool = False,
        trace_id: UUID | None = None,
    ) -> str:
        """把任务消息写入主队列。"""
        ...
        
class LiteratureJob(BaseModel):
    """表示可异步执行的任务。"""
    # 关联的运行记录 ID。
    run_id: int = Field(gt=0)
    # Literature 完成后是否恢复总工作流。
    resume_workflow: bool = False
    # 跨服务追踪 ID。
    trace_id: UUID | None = None
    # 消息队列中的消息 ID。
    message_id: str | None = None


LiteratureJobHandler = Callable[
    [LiteratureJob],
    Awaitable[None],
]


class LiteratureJobConsumer(Protocol):
    """封装 LiteratureJobConsumer 相关的数据和行为。"""
    async def run(
        self,
        handler: LiteratureJobHandler,
    ) -> None:
        """执行当前任务。"""
        ...
