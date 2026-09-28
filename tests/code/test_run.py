import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.run import CodeRunService
from module_agent.code.domain import (
    CodeAgentRequest,
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    CodePaperInput,
    CodeRun,
    CodeRunRepository,
    CodeRunStatus,
    ReproductionPlan,
)


def request() -> CodeAgentRequest:
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


def artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=51,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Test problem",
            implementation_steps=["Implement method"],
        ),
    )


def completed_run() -> CodeRun:
    now = datetime.now(timezone.utc)
    return CodeRun(
        id=3,
        literature_run_id=7,
        attempt=1,
        trace_id=uuid4(),
        status=CodeRunStatus.COMPLETED,
        request=request(),
        artifacts=[artifact()],
        created_at=now,
        started_at=now,
        finished_at=now,
    )


def test_code_run_rejects_completed_state_without_artifacts() -> None:
    now = datetime.now(timezone.utc)

    with pytest.raises(ValidationError, match="requires artifacts"):
        CodeRun(
            literature_run_id=7,
            attempt=1,
            trace_id=uuid4(),
            status=CodeRunStatus.COMPLETED,
            request=request(),
            started_at=now,
            finished_at=now,
        )


def test_code_run_service_persists_running_and_completed_states() -> None:
    agent = AsyncMock(spec=CodeAgent)
    agent.run.return_value = [artifact()]
    repository = AsyncMock(spec=CodeRunRepository)
    repository.get_by_execution.return_value = None

    async def save(run: CodeRun) -> CodeRun:
        return run.model_copy(update={"id": 3})

    repository.save.side_effect = save
    paper_code_status_writer = AsyncMock()
    service = CodeRunService(
        agent,
        repository,
        paper_code_status_writer,
    )
    trace_id = uuid4()

    result = asyncio.run(
        service.execute(request(), attempt=1, trace_id=trace_id)
    )

    assert result.id == 3
    assert result.status is CodeRunStatus.COMPLETED
    assert result.artifacts == [artifact()]
    assert result.trace_id == trace_id
    assert repository.save.await_count == 2
    first = repository.save.await_args_list[0].args[0]
    second = repository.save.await_args_list[1].args[0]
    assert first.status is CodeRunStatus.RUNNING
    assert second.status is CodeRunStatus.COMPLETED
    paper_code_status_writer.write.assert_awaited_once_with([artifact()])


def test_code_run_service_reuses_completed_execution() -> None:
    existing = completed_run()
    agent = AsyncMock(spec=CodeAgent)
    repository = AsyncMock(spec=CodeRunRepository)
    repository.get_by_execution.return_value = existing
    service = CodeRunService(agent, repository)

    result = asyncio.run(
        service.execute(
            request(),
            attempt=1,
            trace_id=existing.trace_id,
        )
    )

    assert result is existing
    agent.run.assert_not_awaited()
    repository.save.assert_not_awaited()


def test_code_run_service_persists_agent_failure() -> None:
    agent = AsyncMock(spec=CodeAgent)
    agent.run.side_effect = RuntimeError("GitHub unavailable")
    repository = AsyncMock(spec=CodeRunRepository)
    repository.get_by_execution.return_value = None

    async def save(run: CodeRun) -> CodeRun:
        return run.model_copy(update={"id": 4})

    repository.save.side_effect = save
    service = CodeRunService(agent, repository)

    with pytest.raises(RuntimeError, match="GitHub unavailable"):
        asyncio.run(
            service.execute(request(), attempt=1, trace_id=uuid4())
        )

    failed = repository.save.await_args_list[1].args[0]
    assert failed.status is CodeRunStatus.FAILED
    assert failed.error == "GitHub unavailable"
    assert failed.finished_at is not None
