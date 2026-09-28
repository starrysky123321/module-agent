import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from module_agent.cli import run_literature_completion_worker as worker_cli


@pytest.mark.parametrize("worker_error", [None, RuntimeError("worker failed")])
def test_completion_worker_closes_all_process_resources(
    monkeypatch: pytest.MonkeyPatch,
    worker_error: RuntimeError | None,
) -> None:
    checkpointer = object()
    start_checkpointer = AsyncMock(return_value=checkpointer)
    close_checkpointer = AsyncMock()
    close_rabbitmq = AsyncMock()
    close_github = AsyncMock()
    close_qwen = AsyncMock()
    dispose_database = AsyncMock()
    run = AsyncMock(side_effect=worker_error)
    worker = MagicMock(run=run)
    worker_class = MagicMock(return_value=worker)
    consumer = object()
    consumer_class = MagicMock(return_value=consumer)

    monkeypatch.setattr(
        worker_cli.postgres_checkpointer_manager,
        "start",
        start_checkpointer,
    )
    monkeypatch.setattr(
        worker_cli.postgres_checkpointer_manager,
        "close",
        close_checkpointer,
    )
    monkeypatch.setattr(
        worker_cli.rabbitmq_connection_manager,
        "close",
        close_rabbitmq,
    )
    monkeypatch.setattr(
        worker_cli.github_client_manager,
        "close",
        close_github,
    )
    monkeypatch.setattr(
        worker_cli.qwen_client_manager,
        "close",
        close_qwen,
    )
    monkeypatch.setattr(
        worker_cli,
        "database_engine",
        SimpleNamespace(dispose=dispose_database),
    )
    monkeypatch.setattr(worker_cli, "LiteratureCompletionWorker", worker_class)
    monkeypatch.setattr(
        worker_cli,
        "RabbitMQLiteratureCompletionConsumer",
        consumer_class,
    )

    if worker_error is None:
        asyncio.run(worker_cli.run_worker())
    else:
        with pytest.raises(RuntimeError, match="worker failed"):
            asyncio.run(worker_cli.run_worker())

    start_checkpointer.assert_awaited_once_with()
    consumer_class.assert_called_once_with(
        worker_cli.rabbitmq_connection_manager
    )
    worker_class.assert_called_once()
    assert worker_class.call_args.kwargs["consumer"] is consumer
    run.assert_awaited_once_with()
    close_checkpointer.assert_awaited_once_with()
    close_rabbitmq.assert_awaited_once_with()
    close_github.assert_awaited_once_with()
    close_qwen.assert_awaited_once_with()
    dispose_database.assert_awaited_once_with()
