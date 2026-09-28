import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from module_agent.code.domain import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationRequest,
    ValidationRun,
    ValidationRunRepository,
    ValidationRunStatus,
    ValidationStatus,
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


def request() -> ValidationRequest:
    return ValidationRequest(
        literature_run_id=7,
        artifacts=[artifact()],
    )


def report() -> ValidationReport:
    item = artifact()
    return ValidationReport(
        literature_run_id=7,
        paper_id=item.paper_id,
        artifact_origin=item.origin,
        artifact_status=item.status,
        mode=ValidationMode.STATIC,
        status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.REPRODUCTION_PLAN,
                status=ValidationCheckStatus.PASSED,
                summary="Plan is complete",
            )
        ],
    )


def test_validation_run_service_persists_lifecycle() -> None:
    agent = AsyncMock(spec=ValidationAgent)
    agent.run.return_value = [report()]
    repository = AsyncMock(spec=ValidationRunRepository)
    repository.get_by_execution.return_value = None

    async def save(run: ValidationRun) -> ValidationRun:
        return run.model_copy(update={"id": 8})

    repository.save.side_effect = save
    service = ValidationRunService(agent, repository)
    trace_id = uuid4()

    result = asyncio.run(
        service.execute(request(), attempt=1, trace_id=trace_id)
    )

    assert result.id == 8
    assert result.status is ValidationRunStatus.COMPLETED
    assert result.reports == [report()]
    assert repository.save.await_count == 2


def test_validation_run_service_reuses_completed_execution() -> None:
    now = datetime.now(timezone.utc)
    existing = ValidationRun(
        id=8,
        literature_run_id=7,
        attempt=1,
        trace_id=uuid4(),
        status=ValidationRunStatus.COMPLETED,
        request=request(),
        reports=[report()],
        started_at=now,
        finished_at=now,
    )
    agent = AsyncMock(spec=ValidationAgent)
    repository = AsyncMock(spec=ValidationRunRepository)
    repository.get_by_execution.return_value = existing
    service = ValidationRunService(agent, repository)

    result = asyncio.run(
        service.execute(
            request(),
            attempt=1,
            trace_id=existing.trace_id,
        )
    )

    assert result is existing
    agent.run.assert_not_awaited()


def test_validation_run_service_persists_agent_failure() -> None:
    agent = AsyncMock(spec=ValidationAgent)
    agent.run.side_effect = TimeoutError("sandbox timed out")
    repository = AsyncMock(spec=ValidationRunRepository)
    repository.get_by_execution.return_value = None

    async def save(run: ValidationRun) -> ValidationRun:
        return run.model_copy(update={"id": 9})

    repository.save.side_effect = save
    service = ValidationRunService(agent, repository)

    with pytest.raises(TimeoutError, match="sandbox timed out"):
        asyncio.run(
            service.execute(request(), attempt=1, trace_id=uuid4())
        )

    failed = repository.save.await_args_list[1].args[0]
    assert failed.status is ValidationRunStatus.FAILED
    assert failed.error == "sandbox timed out"
