from typing import Annotated

from fastapi import APIRouter, Depends, Query

from module_agent.bootstrap.api_dependencies import (
    get_supervisor_observation_query_service,
)
from module_agent.supervision.application.observation_query import (
    SupervisorObservationQueryService,
)
from module_agent.supervision.domain import (
    SupervisorFailureObservationRecord,
    SupervisorObservationListQuery,
    SupervisorObservationStats,
    SupervisorObservationStatsQuery,
    SupervisorPolicyReadiness,
)


supervision_router = APIRouter(
    prefix="/supervision",
    tags=["supervisor-agent"],
)


@supervision_router.get(
    "/observations/stats",
    response_model=SupervisorObservationStats,
)
async def get_observation_stats(
    service: Annotated[
        SupervisorObservationQueryService,
        Depends(get_supervisor_observation_query_service),
    ],
    query: Annotated[SupervisorObservationStatsQuery, Query()],
) -> SupervisorObservationStats:
    """获取对应记录。"""
    return await service.get_stats(
        query.literature_run_id,
        created_from=query.created_from,
        created_to=query.created_to,
    )


@supervision_router.get(
    "/observations",
    response_model=list[SupervisorFailureObservationRecord],
)
async def list_observations(
    service: Annotated[
        SupervisorObservationQueryService,
        Depends(get_supervisor_observation_query_service),
    ],
    query: Annotated[SupervisorObservationListQuery, Query()],
) -> list[SupervisorFailureObservationRecord]:
    """列出符合条件的记录。"""
    return await service.list_observations(query)


@supervision_router.get(
    "/observations/readiness",
    response_model=SupervisorPolicyReadiness,
)
async def get_policy_readiness(
    service: Annotated[
        SupervisorObservationQueryService,
        Depends(get_supervisor_observation_query_service),
    ],
    query: Annotated[SupervisorObservationStatsQuery, Query()],
) -> SupervisorPolicyReadiness:
    """获取对应记录。"""
    return await service.assess_readiness(query)
