from datetime import datetime

from module_agent.supervision.domain import (
    SupervisorFailureObservationRecord,
    SupervisorObservationListQuery,
    SupervisorObservationStats,
    SupervisorObservationStatsReader,
    SupervisorObservationStatsQuery,
    SupervisorPolicyReadiness,
)


class SupervisorObservationQueryService:
    """封装相关应用用例。"""
    def __init__(
        self,
        reader: SupervisorObservationStatsReader,
        *,
        readiness_minimum_observations: int = 100,
        readiness_minimum_success_rate: float = 0.95,
    ) -> None:
        """初始化当前对象。"""
        if readiness_minimum_observations < 1:
            raise ValueError(
                "readiness_minimum_observations must be positive"
            )
        if not 0.0 <= readiness_minimum_success_rate <= 1.0:
            raise ValueError(
                "readiness_minimum_success_rate must be between 0 and 1"
            )
        self.reader = reader
        self.readiness_minimum_observations = (
            readiness_minimum_observations
        )
        self.readiness_minimum_success_rate = (
            readiness_minimum_success_rate
        )

    async def get_stats(
        self,
        literature_run_id: int | None = None,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> SupervisorObservationStats:
        """获取对应记录。"""
        if (
            literature_run_id is not None
            and (
                type(literature_run_id) is not int
                or literature_run_id <= 0
            )
        ):
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        query = SupervisorObservationStatsQuery(
            literature_run_id=literature_run_id,
            created_from=created_from,
            created_to=created_to,
        )
        return await self.reader.get_stats(
            query.literature_run_id,
            created_from=query.created_from,
            created_to=query.created_to,
        )

    async def list_observations(
        self,
        query: SupervisorObservationListQuery,
    ) -> list[SupervisorFailureObservationRecord]:
        """列出符合条件的记录。"""
        return await self.reader.list_observations(query)

    async def assess_readiness(
        self,
        query: SupervisorObservationStatsQuery,
    ) -> SupervisorPolicyReadiness:
        """判断观察数据是否达到人工评审条件。"""
        stats = await self.get_stats(
            query.literature_run_id,
            created_from=query.created_from,
            created_to=query.created_to,
        )
        sample_size_sufficient = (
            stats.total_count
            >= self.readiness_minimum_observations
        )
        success_rate = stats.advice_success_rate
        call_reliability_sufficient = (
            success_rate is not None
            and success_rate
            >= self.readiness_minimum_success_rate
        )
        eligible = (
            sample_size_sufficient
            and call_reliability_sufficient
        )

        if not sample_size_sufficient:
            recommendation = "collect_more_data"
        elif not call_reliability_sufficient:
            recommendation = "investigate_call_failures"
        else:
            recommendation = "review_high_confidence_disagreements"

        return SupervisorPolicyReadiness(
            eligible_for_review=eligible,
            sample_size_sufficient=sample_size_sufficient,
            call_reliability_sufficient=(
                call_reliability_sufficient
            ),
            minimum_observations=(
                self.readiness_minimum_observations
            ),
            minimum_success_rate=(
                self.readiness_minimum_success_rate
            ),
            recommendation=recommendation,
            stats=stats,
        )
