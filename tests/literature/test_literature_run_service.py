import asyncio
from datetime import date, datetime, timezone

import pytest

from module_agent.shared.exceptions import (
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
)
from module_agent.literature.domain.search import (
    SearchRequest,
    SourceSearchMetric,
    SourceSearchOutcome,
)
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.llm_metric import LlmCallMetric, LlmCallOutcome
from module_agent.literature.application.run import LiteratureRunService


def example_request() -> SearchRequest:
    return SearchRequest(
        topic="graph neural networks",
        description="Find representative papers",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["GNN"],
        max_results=10,
    )


class FakeLiteratureRunRepository:
    def __init__(self, run: LiteratureRun | None = None) -> None:
        self.run = run
        self.saved: list[LiteratureRun] = []
        self.paper_replacements: list[
            tuple[int, list[LiteratureRunPaper]]
        ] = []

    async def get_by_id(self, run_id: int) -> LiteratureRun | None:
        if self.run is not None and self.run.id == run_id:
            return self.run
        return None

    async def save(self, run: LiteratureRun) -> LiteratureRun:
        self.saved.append(run)
        if run.id is None:
            return run.model_copy(update={"id": 9})
        return run

    async def replace_papers(
        self,
        run_id: int,
        papers: list[LiteratureRunPaper],
    ) -> None:
        self.paper_replacements.append((run_id, papers))


def test_create_run_saves_and_returns_pending_run() -> None:
    request = example_request()
    repository = FakeLiteratureRunRepository()
    service = LiteratureRunService(repository)

    created = asyncio.run(service.create_run(request))

    assert created.id == 9
    assert created.status is LiteratureRunStatus.PENDING
    assert created.request == request
    assert repository.saved[0].id is None


@pytest.mark.parametrize(
    "initial_status",
    [LiteratureRunStatus.PENDING, LiteratureRunStatus.QUEUED],
)
def test_start_run_moves_startable_run_to_running(
    initial_status: LiteratureRunStatus,
) -> None:
    run = LiteratureRun(id=3, request=example_request(), status=initial_status)
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    started = asyncio.run(service.start_run(3))

    assert started.status is LiteratureRunStatus.RUNNING
    assert started.started_at is not None
    assert started.started_at.tzinfo is not None
    assert repository.saved == [started]


def test_start_run_rejects_completed_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.COMPLETED,
    )
    service = LiteratureRunService(FakeLiteratureRunRepository(run))

    with pytest.raises(ValueError, match="not in a valid state"):
        asyncio.run(service.start_run(3))


def test_start_run_is_idempotent_for_running_run() -> None:
    started_at = datetime(2026, 9, 15, tzinfo=timezone.utc)
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.RUNNING,
        started_at=started_at,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    result = asyncio.run(service.start_run(3))

    assert result is run
    assert result.started_at is started_at
    assert repository.saved == []


def test_complete_run_saves_outputs_and_ordered_papers() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.RUNNING,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)
    source_metric = SourceSearchMetric(
        source="search_openalex",
        query="graph neural network",
        duration_ms=120.5,
        result_count=10,
        outcome=SourceSearchOutcome.SUCCESS,
    )
    llm_metric = LlmCallMetric(
        stage="relevance_scoring",
        model="test-qwen",
        item_count=2,
        duration_ms=50.0,
        timeout_seconds=180.0,
        outcome=LlmCallOutcome.FALLBACK,
        error_type="TimeoutError",
    )
    run_papers = [
        LiteratureRunPaper(
            paper_id=20,
            position=0,
            relevance_score=0.9,
            relevance_reason="Direct match",
            matched_terms=["graph"],
        ),
        LiteratureRunPaper(
            paper_id=10,
            position=1,
            relevance_score=0.7,
            relevance_reason="Partial match",
            matched_terms=["GNN"],
        ),
    ]

    completed = asyncio.run(
        service.complete_run(
            3,
            search_queries=["graph neural network", "GNN"],
            papers=run_papers,
            warnings=["One source was unavailable"],
            source_metrics=[source_metric],
            llm_metrics=[llm_metric],
        )
    )

    assert completed.status is LiteratureRunStatus.COMPLETED
    assert completed.search_queries == ["graph neural network", "GNN"]
    assert completed.warnings == ["One source was unavailable"]
    assert completed.source_metrics == [source_metric]
    assert completed.llm_metrics == [llm_metric]
    assert completed.completed_at is not None
    assert completed.completed_at.tzinfo is not None
    assert repository.paper_replacements == [(3, run_papers)]
    assert repository.saved == [completed]


def test_complete_run_rejects_non_running_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.PENDING,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="not in a valid state"):
        asyncio.run(service.complete_run(3, [], [], []))

    assert repository.paper_replacements == []
    assert repository.saved == []


def test_fail_run_records_normalized_error() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.RUNNING,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    failed = asyncio.run(service.fail_run(3, "  OpenAlex timed out  "))

    assert failed.status is LiteratureRunStatus.FAILED
    assert failed.error == "OpenAlex timed out"
    assert failed.completed_at is not None
    assert failed.completed_at.tzinfo is not None
    assert repository.saved == [failed]


def test_fail_run_rejects_empty_error_without_changing_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.RUNNING,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="cannot be empty"):
        asyncio.run(service.fail_run(3, "   "))

    assert run.status is LiteratureRunStatus.RUNNING
    assert repository.saved == []


def test_fail_run_rejects_non_running_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.COMPLETED,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="not in a valid state"):
        asyncio.run(service.fail_run(3, "unexpected failure"))

    assert repository.saved == []


@pytest.mark.parametrize(
    "initial_status",
    [
        LiteratureRunStatus.PENDING,
        LiteratureRunStatus.QUEUED,
        LiteratureRunStatus.RUNNING,
    ],
)
def test_cancel_run_moves_active_run_to_cancelled(
    initial_status: LiteratureRunStatus,
) -> None:
    run = LiteratureRun(id=3, request=example_request(), status=initial_status)
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    cancelled = asyncio.run(service.cancel_run(3))

    assert cancelled.status is LiteratureRunStatus.CANCELLED
    assert cancelled.completed_at is not None
    assert cancelled.completed_at.tzinfo is not None
    assert repository.saved == [cancelled]


@pytest.mark.parametrize(
    "terminal_status",
    [
        LiteratureRunStatus.COMPLETED,
        LiteratureRunStatus.FAILED,
        LiteratureRunStatus.CANCELLED,
    ],
)
def test_cancel_run_rejects_terminal_run(
    terminal_status: LiteratureRunStatus,
) -> None:
    run = LiteratureRun(id=3, request=example_request(), status=terminal_status)
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="not in a valid state"):
        asyncio.run(service.cancel_run(3))

    assert repository.saved == []


def test_get_run_returns_existing_run_without_saving() -> None:
    run = LiteratureRun(id=3, request=example_request())
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    loaded = asyncio.run(service.get_run(3))

    assert loaded is run
    assert repository.saved == []


def test_get_run_rejects_unknown_id() -> None:
    repository = FakeLiteratureRunRepository()
    service = LiteratureRunService(repository)

    with pytest.raises(LiteratureRunNotFoundError, match="Run with id 99 not found"):
        asyncio.run(service.get_run(99))

    assert repository.saved == []


def test_queue_run_moves_pending_run_to_queued_without_timestamps() -> None:
    run = LiteratureRun(id=3, request=example_request())
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    queued = asyncio.run(service.queue_run(3))

    assert queued.status is LiteratureRunStatus.QUEUED
    assert queued.started_at is None
    assert queued.completed_at is None
    assert repository.saved == [queued]


def test_queue_run_rejects_non_pending_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.RUNNING,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="not in a valid state"):
        asyncio.run(service.queue_run(3))

    assert repository.saved == []


@pytest.mark.parametrize(
    "initial_status",
    [LiteratureRunStatus.QUEUED, LiteratureRunStatus.RUNNING],
)
def test_fail_exhausted_run_records_failure(
    initial_status: LiteratureRunStatus,
) -> None:
    run = LiteratureRun(id=3, request=example_request(), status=initial_status)
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    failed = asyncio.run(
        service.fail_exhausted_run(3, "  Retry limit exceeded  ")
    )

    assert failed.status is LiteratureRunStatus.FAILED
    assert failed.error == "Retry limit exceeded"
    assert failed.completed_at is not None
    assert failed.completed_at.tzinfo is not None
    assert repository.saved == [failed]


def test_fail_exhausted_run_is_idempotent_for_failed_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.FAILED,
        error="Original failure",
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    failed = asyncio.run(service.fail_exhausted_run(3, "Another failure"))

    assert failed is run
    assert failed.error == "Original failure"
    assert repository.saved == []


def test_fail_exhausted_run_rejects_other_terminal_run() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.COMPLETED,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(LiteratureRunStateError, match="not in a valid state"):
        asyncio.run(service.fail_exhausted_run(3, "Retry limit exceeded"))

    assert repository.saved == []


def test_fail_exhausted_run_rejects_empty_error() -> None:
    run = LiteratureRun(
        id=3,
        request=example_request(),
        status=LiteratureRunStatus.QUEUED,
    )
    repository = FakeLiteratureRunRepository(run)
    service = LiteratureRunService(repository)

    with pytest.raises(ValueError, match="cannot be empty"):
        asyncio.run(service.fail_exhausted_run(3, "   "))

    assert run.status is LiteratureRunStatus.QUEUED
    assert repository.saved == []


def test_fail_exhausted_run_rejects_unknown_id() -> None:
    repository = FakeLiteratureRunRepository()
    service = LiteratureRunService(repository)

    with pytest.raises(LiteratureRunNotFoundError, match="Run with id 99 not found"):
        asyncio.run(service.fail_exhausted_run(99, "Retry limit exceeded"))

    assert repository.saved == []
