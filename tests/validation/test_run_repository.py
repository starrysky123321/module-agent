import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.code.domain import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.adapters.database.models.run import (
    ValidationRunModel,
    ValidationRunReportModel,
)
from module_agent.validation.adapters.database.repositories.run import (
    SqlAlchemyValidationRunRepository,
    TransactionalValidationRunRepository,
)
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationRequest,
    ValidationRun,
    ValidationRunStatus,
    ValidationStatus,
)


def _artifact() -> CodeArtifact:
    return CodeArtifact(
        paper_id=51,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Test problem",
            implementation_steps=["Implement method"],
        ),
    )


def _request() -> ValidationRequest:
    return ValidationRequest(literature_run_id=7, artifacts=[_artifact()])


def _report() -> ValidationReport:
    artifact = _artifact()
    return ValidationReport(
        literature_run_id=7,
        paper_id=artifact.paper_id,
        artifact_origin=artifact.origin,
        artifact_status=artifact.status,
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


def _completed_run(*, run_id: int | None = None) -> ValidationRun:
    now = datetime.now(timezone.utc)
    return ValidationRun(
        id=run_id,
        literature_run_id=7,
        attempt=1,
        trace_id=uuid4(),
        status=ValidationRunStatus.COMPLETED,
        request=_request(),
        reports=[_report()],
        created_at=now if run_id else None,
        started_at=now,
        finished_at=now,
    )


def _model(run: ValidationRun) -> ValidationRunModel:
    assert run.id is not None
    assert run.created_at is not None
    model = ValidationRunModel(
        id=run.id,
        literature_run_id=run.literature_run_id,
        attempt=run.attempt,
        trace_id=run.trace_id,
        status=run.status.value,
        request=run.request.model_dump(mode="json"),
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )
    model.reports = [
        ValidationRunReportModel(
            validation_run_id=run.id,
            paper_id=_report().paper_id,
            position=0,
            report=_report().model_dump(mode="json"),
        )
    ]
    return model


def test_validation_repository_saves_new_run_and_reports() -> None:
    session = AsyncMock(spec=AsyncSession)
    created_at = datetime.now(timezone.utc)

    def assign_generated_values(model: ValidationRunModel) -> None:
        model.id = 12
        model.created_at = created_at

    session.add.side_effect = assign_generated_values
    repository = SqlAlchemyValidationRunRepository(session)

    saved = asyncio.run(repository.save(_completed_run()))

    model = session.add.call_args.args[0]
    assert isinstance(model, ValidationRunModel)
    assert model.request["literature_run_id"] == 7
    links = session.add_all.call_args.args[0]
    assert len(links) == 1
    assert links[0].validation_run_id == 12
    assert links[0].paper_id == 51
    assert saved.id == 12
    assert saved.created_at == created_at
    assert session.flush.await_count == 2


def test_validation_repository_updates_existing_run() -> None:
    run = _completed_run(run_id=4)
    model = _model(run)
    model.status = ValidationRunStatus.RUNNING.value
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = model
    repository = SqlAlchemyValidationRunRepository(session)

    saved = asyncio.run(repository.save(run))

    assert saved.id == 4
    assert model.status == ValidationRunStatus.COMPLETED.value
    session.add.assert_not_called()
    session.execute.assert_awaited_once()


def test_validation_repository_rejects_update_for_missing_run() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.get.return_value = None
    repository = SqlAlchemyValidationRunRepository(session)

    with pytest.raises(ValueError, match="does not exist"):
        asyncio.run(repository.save(_completed_run(run_id=99)))


def test_validation_repository_reads_one_and_lists_domain_runs() -> None:
    run = _completed_run(run_id=4)
    model = _model(run)
    result = MagicMock()
    result.scalar_one_or_none.return_value = model
    result.scalars.return_value = [model]
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemyValidationRunRepository(session)

    by_id = asyncio.run(repository.get_by_id(4))
    by_execution = asyncio.run(repository.get_by_execution(7, 1))
    listed = asyncio.run(repository.list_by_literature_run(7))

    assert by_id == run
    assert by_execution == run
    assert listed == [run]


def test_transactional_validation_repository_owns_save_transaction() -> None:
    run = _completed_run(run_id=4)
    session = AsyncMock(spec=AsyncSession)
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=None)
    transaction.__aexit__ = AsyncMock(return_value=None)
    session.begin.return_value = transaction
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    repository = TransactionalValidationRunRepository(session_factory)

    with patch(
        "module_agent.validation.adapters.database.repositories.run."
        "SqlAlchemyValidationRunRepository"
    ) as repository_type:
        repository_type.return_value.save = AsyncMock(return_value=run)
        saved = asyncio.run(repository.save(run))

    assert saved == run
    session.begin.assert_called_once_with()
    transaction.__aexit__.assert_awaited_once()
    session_context.__aexit__.assert_awaited_once()


def test_transactional_validation_repository_delegates_reads() -> None:
    run = _completed_run(run_id=4)
    session = AsyncMock(spec=AsyncSession)
    session_context = MagicMock()
    session_context.__aenter__ = AsyncMock(return_value=session)
    session_context.__aexit__ = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session_context)
    repository = TransactionalValidationRunRepository(session_factory)

    with patch(
        "module_agent.validation.adapters.database.repositories.run."
        "SqlAlchemyValidationRunRepository"
    ) as repository_type:
        inner = repository_type.return_value
        inner.get_by_id = AsyncMock(return_value=run)
        inner.get_by_execution = AsyncMock(return_value=run)
        inner.list_by_literature_run = AsyncMock(return_value=[run])
        assert asyncio.run(repository.get_by_id(4)) == run
        assert asyncio.run(repository.get_by_execution(7, 1)) == run
        assert asyncio.run(repository.list_by_literature_run(7)) == [run]

    assert session_factory.call_count == 3
    inner.get_by_id.assert_awaited_once_with(4)
    inner.get_by_execution.assert_awaited_once_with(7, 1)
    inner.list_by_literature_run.assert_awaited_once_with(7)
