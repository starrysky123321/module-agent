"""A failed/active deletion must never silently remove task history."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.shared.exceptions import AppException
from module_agent.workflow.deletion import TaskDeletionService
from module_agent.workflow.adapters.database.deletion import SqlAlchemyTaskDeletionRepository


@pytest.mark.parametrize("run_id", [True, 0, -1, "1"])
def test_invalid_id_never_reaches_storage(run_id):
    repository = AsyncMock()
    checkpoint = AsyncMock()
    with pytest.raises(ValueError):
        asyncio.run(TaskDeletionService(repository, checkpoint).delete(run_id))
    repository.delete_if_inactive.assert_not_awaited()
    checkpoint.assert_not_awaited()


def test_database_rejection_preserves_checkpoint():
    repository = AsyncMock()
    repository.delete_if_inactive.side_effect = AppException("active", "task_is_active", 409)
    checkpoint = AsyncMock()
    with pytest.raises(AppException):
        asyncio.run(TaskDeletionService(repository, checkpoint).delete(9))
    checkpoint.assert_not_awaited()


def test_checkpoint_cleanup_failure_can_be_retried_after_record_deletion():
    repository = AsyncMock()
    checkpoint = AsyncMock(side_effect=[None, RuntimeError("storage unavailable"), None, None])
    service = TaskDeletionService(repository, checkpoint)
    with pytest.raises(AppException) as error:
        asyncio.run(service.delete(9))
    assert error.value.status_code == 503
    assert error.value.code == "task_checkpoint_cleanup_pending"
    assert "记录已删除" in error.value.message
    asyncio.run(service.delete(9))
    assert checkpoint.await_args_list == [
        call("workflow.thread:9"),
        call("literature-run:9"),
        call("workflow.thread:9"),
        call("literature-run:9"),
    ]


def repository_case(literature="completed", workflow="completed", code=(), validation=(), experiment=None):
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [literature, workflow, experiment]
    code_rows, validation_rows = MagicMock(), MagicMock()
    code_rows.all.return_value = list(code)
    validation_rows.all.return_value = list(validation)
    session.scalars.side_effect = [code_rows, validation_rows]
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return SqlAlchemyTaskDeletionRepository(factory), session


@pytest.mark.parametrize("literature,workflow,code,validation", [
    ("queued", None, (), ()), ("running", "cancelled", (), ()),
    ("completed", "running", (), ()),
    ("completed", "waiting_for_code", (), ()),
    ("completed", "waiting_for_literature", (), ()),
    ("completed", "cancelled", ("running",), ()),
    ("completed", "failed", (), ("running",)),
])
def test_active_states_are_rejected(literature, workflow, code, validation):
    repository, session = repository_case(literature, workflow, code, validation)
    with pytest.raises(AppException) as error:
        asyncio.run(repository.delete_if_inactive(9))
    assert error.value.status_code == 409
    session.execute.assert_not_awaited()


@pytest.mark.parametrize("literature,workflow", [
    ("pending", None), ("completed", "waiting_for_selection"),
    ("completed", "completed"), ("failed", "failed"),
    ("cancelled", "cancelled"), ("completed", "timed_out"),
])
def test_only_exact_task_is_deleted_under_row_locks(literature, workflow):
    repository, session = repository_case(literature, workflow)
    asyncio.run(repository.delete_if_inactive(9))
    statement = session.execute.call_args.args[0]
    assert statement.table.name == "literature_runs"
    assert statement.compile().params == {"id_1": 9}
    assert all("FOR UPDATE" in str(call.args[0]) for call in session.scalar.call_args_list[:2])
    session.begin.assert_called_once()


def test_already_deleted_record_is_safe_to_retry():
    repository, session = repository_case(literature=None)
    asyncio.run(repository.delete_if_inactive(9))
    session.execute.assert_not_awaited()
    session.scalars.assert_not_awaited()


def test_active_experiment_prevents_parent_deletion():
    repository, session = repository_case(experiment="active-experiment-uuid")
    with pytest.raises(AppException):
        asyncio.run(repository.delete_if_inactive(9))
    session.execute.assert_not_awaited()
