from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel, Field


class LiteratureCompletedEvent(BaseModel):
    """表示可发布的领域事件。"""
    # 关联的运行记录 ID。
    run_id: int = Field(gt=0)


class LiteratureCompletionPublisher(Protocol):
    """封装 LiteratureCompletionPublisher 相关的数据和行为。"""
    async def publish(self, run_id: int) -> str:
        """发布对应消息。"""
        ...


LiteratureCompletionHandler = Callable[
    [LiteratureCompletedEvent],
    Awaitable[None],
]


class LiteratureCompletionConsumer(Protocol):
    """封装 LiteratureCompletionConsumer 相关的数据和行为。"""
    async def run(
        self,
        handler: LiteratureCompletionHandler,
    ) -> None:
        """执行当前任务。"""
        ...
