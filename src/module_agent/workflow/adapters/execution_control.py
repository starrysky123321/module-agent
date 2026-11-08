from module_agent.shared.exceptions import WorkflowLifecycleNotFoundError
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRunStatus,
    WorkflowControlStatus,
)
from module_agent.workflow.lifecycle_service import ModuleWorkflowLifecycleService


class WorkflowExecutionControl:
    """以数据库中的取消状态/截止时间控制独立文献和代码 Worker。"""

    def __init__(self, lifecycle: ModuleWorkflowLifecycleService) -> None:
        self.lifecycle = lifecycle

    async def __call__(self, run_id: int) -> bool:
        try:
            run = await self.lifecycle.get(run_id)
        except WorkflowLifecycleNotFoundError:
            # 独立 Code API 可以没有 Module Workflow。
            return True
        if run.status in {
            ModuleWorkflowRunStatus.COMPLETED,
            ModuleWorkflowRunStatus.FAILED,
            ModuleWorkflowRunStatus.CANCELLED,
            ModuleWorkflowRunStatus.TIMED_OUT,
        }:
            return False
        return (
            await self.lifecycle.check_control(run_id) is WorkflowControlStatus.ACTIVE
        )
