import asyncio
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver

from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)
from module_agent.code.application.agent import CodeAgent
from module_agent.literature.application.dispatch import (
    LiteratureRunDispatcher,
)
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.workflow.observation import (
    WorkflowNodeExecution,
    WorkflowNodeExecutionRecorder,
    WorkflowNodeExecutionStatus,
)


def test_graph_records_completed_and_interrupted_nodes() -> None:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.return_value = "message-7"
    recorder = AsyncMock(spec=WorkflowNodeExecutionRecorder)

    async def return_execution(
        execution: WorkflowNodeExecution,
    ) -> WorkflowNodeExecution:
        return execution

    recorder.record.side_effect = return_execution
    graph = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=AsyncMock(spec=CodeAgent),
        code_input_loader=AsyncMock(spec=SelectedPaperCodeInputLoader),
        validation_agent=build_validation_agent(
            workspace_root=Path.cwd()
        ),
        checkpointer=InMemorySaver(),
        node_execution_recorder=recorder,
    ).build()
    trace_id = uuid4()

    asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "trace_id": str(trace_id),
                "status": "searching_literature",
                "next_step": "literature",
            },
            {"configurable": {"thread_id": "observed-workflow"}},
        )
    )

    executions = [call.args[0] for call in recorder.record.await_args_list]
    assert [execution.node for execution in executions] == [
        "supervisor",
        "literature_dispatch",
        "supervisor",
        "literature_wait",
    ]
    assert executions[-1].status is WorkflowNodeExecutionStatus.INTERRUPTED
    assert all(execution.trace_id == trace_id for execution in executions)
    assert all(execution.duration_ms >= 0 for execution in executions)
    assert all("code_requirements" not in execution.input_summary for execution in executions)
