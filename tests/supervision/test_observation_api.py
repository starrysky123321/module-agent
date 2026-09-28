import asyncio
from unittest.mock import AsyncMock

import httpx

from module_agent.bootstrap.api_dependencies import (
    get_supervisor_observation_query_service,
)
from module_agent.main import create_app
from module_agent.supervision.application.observation_query import (
    SupervisorObservationQueryService,
)
from module_agent.supervision.domain import (
    SupervisorObservationStats,
    SupervisorPolicyReadiness,
)


def send_get(path: str, service: AsyncMock) -> httpx.Response:
    application = create_app()
    application.dependency_overrides[
        get_supervisor_observation_query_service
    ] = lambda: service

    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(request())


def empty_stats(
    literature_run_id: int | None = None,
) -> SupervisorObservationStats:
    return SupervisorObservationStats(
        literature_run_id=literature_run_id,
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


def test_stats_endpoint_returns_all_observations() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)
    service.get_stats.return_value = empty_stats()

    response = send_get(
        "/api/supervision/observations/stats",
        service,
    )

    assert response.status_code == 200
    assert response.json()["total_count"] == 0
    assert response.json()["advice_success_rate"] is None
    service.get_stats.assert_awaited_once_with(
        None,
        created_from=None,
        created_to=None,
    )


def test_stats_endpoint_filters_by_literature_run_id() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)
    service.get_stats.return_value = empty_stats(12)

    response = send_get(
        "/api/supervision/observations/stats?literature_run_id=12",
        service,
    )

    assert response.status_code == 200
    assert response.json()["literature_run_id"] == 12
    service.get_stats.assert_awaited_once_with(
        12,
        created_from=None,
        created_to=None,
    )


def test_stats_endpoint_rejects_non_positive_run_id() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)

    response = send_get(
        "/api/supervision/observations/stats?literature_run_id=0",
        service,
    )

    assert response.status_code == 422
    service.get_stats.assert_not_awaited()


def test_observation_list_endpoint_parses_filters() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)
    service.list_observations.return_value = []

    response = send_get(
        "/api/supervision/observations"
        "?literature_run_id=12&failure_category=timeout"
        "&agrees=false&min_confidence=0.8&limit=20&offset=5",
        service,
    )

    assert response.status_code == 200
    assert response.json() == []
    query = service.list_observations.await_args.args[0]
    assert query.literature_run_id == 12
    assert query.failure_category.value == "timeout"
    assert query.agrees is False
    assert query.min_confidence == 0.8
    assert query.limit == 20
    assert query.offset == 5


def test_readiness_endpoint_returns_review_status() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)
    service.assess_readiness.return_value = SupervisorPolicyReadiness(
        eligible_for_review=False,
        sample_size_sufficient=False,
        call_reliability_sufficient=False,
        minimum_observations=100,
        minimum_success_rate=0.95,
        recommendation="collect_more_data",
        stats=empty_stats(),
    )

    response = send_get(
        "/api/supervision/observations/readiness",
        service,
    )

    assert response.status_code == 200
    assert response.json()["eligible_for_review"] is False
    query = service.assess_readiness.await_args.args[0]
    assert query.literature_run_id is None


def test_stats_endpoint_rejects_timestamp_without_timezone() -> None:
    service = AsyncMock(spec=SupervisorObservationQueryService)

    response = send_get(
        "/api/supervision/observations/stats"
        "?created_from=2026-09-27T12:00:00",
        service,
    )

    assert response.status_code == 422
    service.get_stats.assert_not_awaited()
