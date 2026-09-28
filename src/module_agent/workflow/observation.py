from datetime import datetime
from enum import StrEnum
from collections.abc import Mapping
from typing import Annotated, Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from module_agent.workflow.domain import SupervisorStep


class WorkflowNodeExecutionStatus(StrEnum):
    """定义可用的状态值。"""
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class WorkflowNodeExecution(BaseModel):
    """封装 WorkflowNodeExecution 相关的数据和行为。"""
    # 记录主键。
    id: Annotated[int, Field(gt=0)] | None = None
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 跨服务追踪 ID。
    trace_id: UUID
    # LangGraph 节点名称。
    node: Annotated[str, Field(min_length=1, max_length=64)]
    # 当前执行次数。
    attempt: Annotated[int, Field(ge=1)] = 1
    # 当前处理状态。
    status: WorkflowNodeExecutionStatus
    # 操作耗时，单位为毫秒。
    duration_ms: Annotated[float, Field(ge=0)]
    # 节点输入的脱敏摘要。
    input_summary: dict[str, Any] = Field(default_factory=dict)
    # 节点输出的脱敏摘要。
    output_summary: dict[str, Any] = Field(default_factory=dict)
    # 失败时的错误信息。
    error: str | None = None
    # 记录创建时间。
    created_at: datetime | None = None


class WorkflowNodeExecutionRecorder(Protocol):
    """封装 WorkflowNodeExecutionRecorder 相关的数据和行为。"""
    async def record(
        self,
        execution: WorkflowNodeExecution,
    ) -> WorkflowNodeExecution:
        """记录本次观察结果。"""
        ...


class WorkflowNodeExecutionReader(Protocol):
    """封装 WorkflowNodeExecutionReader 相关的数据和行为。"""
    async def list_by_workflow(
        self,
        literature_run_id: int,
    ) -> list[WorkflowNodeExecution]:
        """列出符合条件的记录。"""
        ...


class WorkflowRuntimeMetrics(BaseModel):
    """保存运行统计指标。"""
    # 统计范围内的工作流总数。
    total_workflows: Annotated[int, Field(ge=0)]
    # 按状态分组的任务数量。
    status_counts: dict[str, Annotated[int, Field(ge=0)]]
    # 任务成功率。
    success_rate: Annotated[float, Field(ge=0, le=1)]
    # 工作流平均耗时，单位为毫秒。
    average_workflow_duration_ms: float | None = Field(
        default=None,
        ge=0,
    )
    # 节点执行总次数。
    node_executions: Annotated[int, Field(ge=0)]
    # 失败的节点执行次数。
    failed_node_executions: Annotated[int, Field(ge=0)]
    # 节点平均耗时，单位为毫秒。
    average_node_duration_ms: float | None = Field(
        default=None,
        ge=0,
    )


def summarize_workflow_state(
    state: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a small, non-sensitive state summary for observability."""
    return {
        "status": state.get("status"),
        "next_step": state.get("next_step"),
        "selected_paper_count": len(
            state.get("selected_paper_ids") or []
        ),
        "code_artifact_count": len(state.get("code_artifacts") or []),
        "validation_report_count": len(
            state.get("validation_reports") or []
        ),
        "has_failure": state.get("failure") is not None,
    }


def workflow_node_attempt(
    name: str,
    state: Mapping[str, Any],
    output: Mapping[str, Any] | None,
) -> int:
    """Resolve the logical retry attempt represented by a graph node."""
    step_by_node = {
        "literature_dispatch": SupervisorStep.LITERATURE.value,
        "code": SupervisorStep.CODE.value,
        "code_wait": SupervisorStep.CODE.value,
        "validation": SupervisorStep.VALIDATION.value,
    }
    attempts = (output or {}).get("attempts") or state.get("attempts") or {}
    step = step_by_node.get(name)
    if step is None:
        return 1
    return max(int(attempts.get(step, 1)), 1)
