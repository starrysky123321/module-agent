from pydantic import BaseModel

from module_agent.literature.domain.run import LiteratureRunStatus


class LiteratureDispatchResponse(BaseModel):
    """表示一次响应结果。"""
    # 关联的运行记录 ID。
    run_id: int
    # 消息队列中的消息 ID。
    message_id: str
    # 当前处理状态。
    status: LiteratureRunStatus = LiteratureRunStatus.QUEUED
