import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from module_agent.shared.execution_control import run_with_control
from module_agent.shared.exceptions import WorkflowLifecycleNotFoundError
from module_agent.workflow.adapters.execution_control import WorkflowExecutionControl
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRunStatus,
    WorkflowControlStatus,
)


@pytest.mark.parametrize(
    "status",
    [
        ModuleWorkflowRunStatus.COMPLETED,
        ModuleWorkflowRunStatus.FAILED,
        ModuleWorkflowRunStatus.CANCELLED,
        ModuleWorkflowRunStatus.TIMED_OUT,
    ],
)
def test_finished_workflow_cannot_begin_another_worker_execution(status):
    lifecycle = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(status=status)),
        check_control=AsyncMock(),
    )
    assert asyncio.run(WorkflowExecutionControl(lifecycle)(1)) is False
    lifecycle.check_control.assert_not_awaited()


def test_standalone_agent_without_workflow_is_supported():
    lifecycle = SimpleNamespace(
        get=AsyncMock(side_effect=WorkflowLifecycleNotFoundError(1))
    )
    assert asyncio.run(WorkflowExecutionControl(lifecycle)(1)) is True


def test_workflow_deadline_is_observed_during_execution():
    lifecycle = SimpleNamespace(
        get=AsyncMock(
            return_value=SimpleNamespace(
                status=ModuleWorkflowRunStatus.WAITING_FOR_CODE
            )
        ),
        check_control=AsyncMock(return_value=WorkflowControlStatus.TIMED_OUT),
    )
    assert asyncio.run(WorkflowExecutionControl(lifecycle)(1)) is False


def test_outer_cancellation_does_not_leave_detached_work():
    async def exercise():
        started = asyncio.Event()
        stopped = asyncio.Event()

        async def operation():
            started.set()
            try:
                await asyncio.sleep(10)
            finally:
                stopped.set()

        task = asyncio.create_task(
            run_with_control(operation, AsyncMock(return_value=True), poll_seconds=0.01)
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stopped.is_set()

    asyncio.run(exercise())


def test_control_failure_stops_work_instead_of_leaving_it_running():
    async def exercise():
        stopped = []

        async def operation():
            try:
                await asyncio.sleep(10)
            finally:
                stopped.append(True)

        with pytest.raises(RuntimeError, match="control unavailable"):
            await run_with_control(
                operation,
                AsyncMock(side_effect=[True, RuntimeError("control unavailable")]),
                poll_seconds=0.01,
            )
        assert stopped

    asyncio.run(exercise())
