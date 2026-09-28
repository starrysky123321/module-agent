import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

from module_agent.code.application.recovery import CodeRunRecoveryService
from module_agent.code.domain import (
    CodeAgentRequest,
    CodePaperInput,
    CodeRun,
    CodeRunRepository,
    CodeRunStatus,
)


def _request() -> CodeAgentRequest:
    return CodeAgentRequest(
        literature_run_id=7,
        papers=[
            CodePaperInput(
                paper_id=51,
                source="openalex",
                source_id="W51",
                title="Paper 51",
            )
        ],
    )


def _running_run() -> CodeRun:
    return CodeRun(
        id=3,
        literature_run_id=7,
        attempt=1,
        trace_id=uuid4(),
        status=CodeRunStatus.RUNNING,
        request=_request(),
        started_at=datetime.now(UTC),
    )


def test_recovery_marks_running_execution_failed() -> None:
    repository = AsyncMock(spec=CodeRunRepository)
    repository.get_by_execution.return_value = _running_run()
    repository.save.side_effect = lambda run: run
    service = CodeRunRecoveryService(repository)

    result = asyncio.run(
        service.fail_exhausted_execution(
            _request(),
            attempt=1,
            trace_id=uuid4(),
            error="delivery limit exhausted",
        )
    )

    assert result.status is CodeRunStatus.FAILED
    assert result.error == "delivery limit exhausted"
    assert result.finished_at is not None
    repository.save.assert_awaited_once()


def test_recovery_creates_failed_execution_when_run_was_not_persisted() -> None:
    repository = AsyncMock(spec=CodeRunRepository)
    repository.get_by_execution.return_value = None
    repository.save.side_effect = lambda run: run.model_copy(update={"id": 4})
    service = CodeRunRecoveryService(repository)
    trace_id = uuid4()

    result = asyncio.run(
        service.fail_exhausted_execution(
            _request(),
            attempt=2,
            trace_id=trace_id,
            error="delivery limit exhausted",
        )
    )

    assert result.id == 4
    assert result.status is CodeRunStatus.FAILED
    assert result.trace_id == trace_id


def test_recovery_reuses_terminal_execution() -> None:
    repository = AsyncMock(spec=CodeRunRepository)
    failed = _running_run().model_copy(
        update={
            "status": CodeRunStatus.FAILED,
            "error": "original failure",
            "finished_at": datetime.now(UTC),
        }
    )
    repository.get_by_execution.return_value = failed
    service = CodeRunRecoveryService(repository)

    result = asyncio.run(
        service.fail_exhausted_execution(
            _request(),
            attempt=1,
            trace_id=uuid4(),
            error="delivery limit exhausted",
        )
    )

    assert result is failed
    repository.save.assert_not_awaited()
