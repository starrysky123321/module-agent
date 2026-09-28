from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from module_agent.workflow.adapters.database.node_execution_model import (
    WorkflowNodeExecutionModel,
)
from module_agent.workflow.observation import (
    WorkflowNodeExecution,
    WorkflowNodeExecutionStatus,
    WorkflowRuntimeMetrics,
)
from module_agent.workflow.adapters.database.model import (
    ModuleWorkflowRunModel,
)
from module_agent.workflow.lifecycle import ModuleWorkflowRunStatus


class SqlAlchemyWorkflowNodeExecutionRepository:
    """Store node telemetry independently from workflow transactions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """初始化当前对象。"""
        self.session_factory = session_factory

    async def record(
        self,
        execution: WorkflowNodeExecution,
    ) -> WorkflowNodeExecution:
        """记录本次观察结果。"""
        async with self.session_factory() as session:
            async with session.begin():
                model = WorkflowNodeExecutionModel(
                    literature_run_id=execution.literature_run_id,
                    trace_id=execution.trace_id,
                    node=execution.node,
                    attempt=execution.attempt,
                    status=execution.status.value,
                    duration_ms=execution.duration_ms,
                    input_summary=execution.input_summary,
                    output_summary=execution.output_summary,
                    error=execution.error,
                )
                session.add(model)
                await session.flush()
                return self._to_domain(model)

    async def list_by_workflow(
        self,
        literature_run_id: int,
    ) -> list[WorkflowNodeExecution]:
        """列出符合条件的记录。"""
        async with self.session_factory() as session:
            result = await session.execute(
                select(WorkflowNodeExecutionModel)
                .where(
                    WorkflowNodeExecutionModel.literature_run_id
                    == literature_run_id
                )
                .order_by(
                    WorkflowNodeExecutionModel.created_at,
                    WorkflowNodeExecutionModel.id,
                )
            )
            return [
                self._to_domain(model) for model in result.scalars()
            ]

    async def metrics(self) -> WorkflowRuntimeMetrics:
        """统计工作流成功率和节点耗时。"""
        async with self.session_factory() as session:
            status_rows = (
                await session.execute(
                    select(
                        ModuleWorkflowRunModel.status,
                        func.count(ModuleWorkflowRunModel.literature_run_id),
                    ).group_by(ModuleWorkflowRunModel.status)
                )
            ).all()
            status_counts = {
                str(status): int(count) for status, count in status_rows
            }
            total = sum(status_counts.values())
            terminal = sum(
                status_counts.get(status.value, 0)
                for status in (
                    ModuleWorkflowRunStatus.COMPLETED,
                    ModuleWorkflowRunStatus.FAILED,
                    ModuleWorkflowRunStatus.CANCELLED,
                    ModuleWorkflowRunStatus.TIMED_OUT,
                )
            )
            completed = status_counts.get(
                ModuleWorkflowRunStatus.COMPLETED.value,
                0,
            )
            workflow_duration = await session.scalar(
                select(
                    func.avg(
                        func.extract(
                            "epoch",
                            ModuleWorkflowRunModel.finished_at
                            - ModuleWorkflowRunModel.created_at,
                        )
                        * 1000
                    )
                ).where(ModuleWorkflowRunModel.finished_at.is_not(None))
            )
            node_metrics = (
                await session.execute(
                    select(
                        func.count(WorkflowNodeExecutionModel.id),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        WorkflowNodeExecutionModel.status
                                        == WorkflowNodeExecutionStatus.FAILED.value,
                                        1,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.avg(WorkflowNodeExecutionModel.duration_ms),
                    )
                )
            ).one()
            node_count, failed_node_count, node_duration = node_metrics
            return WorkflowRuntimeMetrics(
                total_workflows=total,
                status_counts=status_counts,
                success_rate=(completed / terminal if terminal else 0.0),
                average_workflow_duration_ms=(
                    float(workflow_duration)
                    if workflow_duration is not None
                    else None
                ),
                node_executions=int(node_count),
                failed_node_executions=int(failed_node_count),
                average_node_duration_ms=(
                    float(node_duration)
                    if node_duration is not None
                    else None
                ),
            )

    @staticmethod
    def _to_domain(
        model: WorkflowNodeExecutionModel,
    ) -> WorkflowNodeExecution:
        return WorkflowNodeExecution(
            id=model.id,
            literature_run_id=model.literature_run_id,
            trace_id=model.trace_id,
            node=model.node,
            attempt=model.attempt,
            status=WorkflowNodeExecutionStatus(model.status),
            duration_ms=model.duration_ms,
            input_summary=model.input_summary,
            output_summary=model.output_summary,
            error=model.error,
            created_at=model.created_at,
        )
