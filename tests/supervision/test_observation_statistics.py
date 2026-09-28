import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.supervision.adapters.database.repositories.observation import (
    SqlAlchemySupervisorObservationRepository,
)
from module_agent.supervision.application.observation_query import (
    SupervisorObservationQueryService,
)
from module_agent.supervision.domain import (
    SupervisorFailureCategoryStats,
    SupervisorObservationListQuery,
    SupervisorObservationStats,
    SupervisorObservationStatsQuery,
    SupervisorObservationStatsReader,
    WorkflowFailureCategory,
)
from module_agent.supervision.adapters.database.models.observation import (
    SupervisorFailureObservationModel,
)


SUMMARY_ROW = (10, 8, 6, 2, 5, 2, 5, 3, 0.81234, 125.567)
CATEGORY_ROWS = [
    (
        WorkflowFailureCategory.TIMEOUT.value,
        6,
        5,
        4,
        1,
        4,
        1,
        3,
        2,
        0.9,
        100.0,
    ),
    (
        WorkflowFailureCategory.TRANSIENT_EXTERNAL.value,
        4,
        3,
        2,
        1,
        1,
        1,
        2,
        1,
        0.7,
        168.0,
    ),
]


def repository_with_results(
    summary_row=SUMMARY_ROW,
    category_rows=CATEGORY_ROWS,
):
    summary_result = MagicMock()
    summary_result.one.return_value = summary_row
    category_result = MagicMock()
    category_result.all.return_value = category_rows
    session = AsyncMock(spec=AsyncSession)
    session.execute.side_effect = [summary_result, category_result]
    return SqlAlchemySupervisorObservationRepository(session), session


def test_repository_calculates_overall_and_category_rates() -> None:
    repository, session = repository_with_results()

    stats = asyncio.run(repository.get_stats())

    assert stats.total_count == 10
    assert stats.advice_success_count == 8
    assert stats.advice_error_count == 2
    assert stats.advice_success_rate == 0.8
    assert stats.agreement_rate == 0.75
    assert stats.high_confidence_disagreement_rate == 0.4
    assert stats.average_confidence == 0.8123
    assert stats.average_latency_ms == 125.567
    assert [item.category for item in stats.by_failure_category] == [
        WorkflowFailureCategory.TIMEOUT,
        WorkflowFailureCategory.TRANSIENT_EXTERNAL,
    ]
    assert stats.by_failure_category[0].agreement_rate == 0.8
    assert stats.by_failure_category[1].advice_error_count == 1
    assert session.execute.await_count == 2


def test_repository_filters_both_queries_by_run_id() -> None:
    repository, session = repository_with_results()

    stats = asyncio.run(repository.get_stats(42))

    assert stats.literature_run_id == 42
    statements = [
        str(call.args[0])
        for call in session.execute.await_args_list
    ]
    assert all(
        "literature_run_id" in statement
        for statement in statements
    )


def test_repository_returns_null_rates_when_no_observations_exist() -> None:
    repository, _ = repository_with_results(
        summary_row=(0, 0, 0, 0, 0, 0, 0, 0, None, None),
        category_rows=[],
    )

    stats = asyncio.run(repository.get_stats())

    assert stats.total_count == 0
    assert stats.advice_success_rate is None
    assert stats.agreement_rate is None
    assert stats.high_confidence_disagreement_rate is None
    assert stats.average_confidence is None
    assert stats.average_latency_ms is None
    assert stats.by_failure_category == []


def test_repository_lists_filtered_observations() -> None:
    created_at = datetime(2026, 9, 27, tzinfo=timezone.utc)
    model = SupervisorFailureObservationModel(
        id=11,
        literature_run_id=42,
        failure_step="validation",
        failure_category="timeout",
        failure_message="Validation timed out",
        failure_retryable=True,
        failure_attempt=2,
        failure_error_type="TimeoutError",
        rule_disposition="retry",
        jev_disposition="stop",
        confidence=0.91,
        retry_probability=0.09,
        stop_probability=0.91,
        model="jev-1.13.0",
        request_id="req-11",
        latency_ms=125,
        agrees=False,
        meets_confidence_threshold=True,
        error=None,
        created_at=created_at,
    )
    scalar_result = MagicMock()
    scalar_result.all.return_value = [model]
    result = MagicMock()
    result.scalars.return_value = scalar_result
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = result
    repository = SqlAlchemySupervisorObservationRepository(session)
    query = SupervisorObservationListQuery(
        literature_run_id=42,
        failure_category=WorkflowFailureCategory.TIMEOUT,
        agrees=False,
        min_confidence=0.8,
        limit=10,
    )

    records = asyncio.run(repository.list_observations(query))

    assert len(records) == 1
    assert records[0].id == 11
    assert records[0].failure.retryable is True
    assert records[0].advice is not None
    assert records[0].advice.confidence == 0.91
    assert records[0].agrees is False
    statement = str(session.execute.await_args.args[0])
    assert "literature_run_id" in statement
    assert "failure_category" in statement
    assert "confidence" in statement


def test_query_service_validates_run_id_and_delegates() -> None:
    reader = AsyncMock(spec=SupervisorObservationStatsReader)
    reader.get_stats.return_value = SupervisorObservationStats(
        literature_run_id=7,
        total_count=0,
        advice_success_count=0,
        advice_error_count=0,
        agreement_count=0,
        disagreement_count=0,
        high_confidence_count=0,
        high_confidence_disagreement_count=0,
        retry_advice_count=0,
        stop_advice_count=0,
    )
    service = SupervisorObservationQueryService(reader)

    result = asyncio.run(service.get_stats(7))

    assert result.literature_run_id == 7
    reader.get_stats.assert_awaited_once_with(
        7,
        created_from=None,
        created_to=None,
    )

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(service.get_stats(0))


@pytest.mark.parametrize(
    (
        "total_count",
        "success_rate",
        "expected_eligible",
        "expected_recommendation",
    ),
    [
        (20, 1.0, False, "collect_more_data"),
        (100, 0.8, False, "investigate_call_failures"),
        (
            100,
            0.98,
            True,
            "review_high_confidence_disagreements",
        ),
    ],
)
def test_readiness_requires_sample_size_and_call_reliability(
    total_count: int,
    success_rate: float,
    expected_eligible: bool,
    expected_recommendation: str,
) -> None:
    success_count = round(total_count * success_rate)
    reader = AsyncMock(spec=SupervisorObservationStatsReader)
    reader.get_stats.return_value = SupervisorObservationStats(
        total_count=total_count,
        advice_success_count=success_count,
        advice_error_count=total_count - success_count,
        agreement_count=success_count,
        disagreement_count=0,
        high_confidence_count=success_count,
        high_confidence_disagreement_count=0,
        retry_advice_count=success_count,
        stop_advice_count=0,
        advice_success_rate=success_rate,
        agreement_rate=1.0,
        high_confidence_disagreement_rate=0.0,
        by_failure_category=[
            SupervisorFailureCategoryStats(
                category=WorkflowFailureCategory.TIMEOUT,
                total_count=total_count,
                advice_success_count=success_count,
                advice_error_count=total_count - success_count,
                agreement_count=success_count,
                disagreement_count=0,
                high_confidence_count=success_count,
                high_confidence_disagreement_count=0,
                retry_advice_count=success_count,
                stop_advice_count=0,
                advice_success_rate=success_rate,
                agreement_rate=1.0,
                high_confidence_disagreement_rate=0.0,
            )
        ],
    )
    service = SupervisorObservationQueryService(
        reader,
        readiness_minimum_observations=100,
        readiness_minimum_success_rate=0.95,
    )

    readiness = asyncio.run(
        service.assess_readiness(SupervisorObservationStatsQuery())
    )

    assert readiness.eligible_for_review is expected_eligible
    assert readiness.recommendation == expected_recommendation


def test_observation_query_rejects_naive_or_reversed_timestamps() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SupervisorObservationStatsQuery(
            created_from=datetime(2026, 9, 27)
        )

    with pytest.raises(ValidationError, match="cannot be after"):
        SupervisorObservationStatsQuery(
            created_from=datetime(2026, 9, 28, tzinfo=timezone.utc),
            created_to=datetime(2026, 9, 27, tzinfo=timezone.utc),
        )


def test_statistics_reject_inconsistent_counts() -> None:
    with pytest.raises(ValidationError, match="must equal total"):
        SupervisorFailureCategoryStats(
            category=WorkflowFailureCategory.TIMEOUT,
            total_count=2,
            advice_success_count=2,
            advice_error_count=1,
            agreement_count=1,
            disagreement_count=1,
            high_confidence_count=0,
            high_confidence_disagreement_count=0,
            retry_advice_count=1,
            stop_advice_count=1,
        )
