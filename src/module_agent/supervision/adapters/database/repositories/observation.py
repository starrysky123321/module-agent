from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from module_agent.supervision.adapters.database.models.observation import (
    SupervisorFailureObservationModel,
)
from module_agent.supervision.domain import (
    FailureDisposition,
    SupervisorFailureObservation,
    SupervisorFailureCategoryStats,
    SupervisorFailureObservationRecord,
    SupervisorObservationListQuery,
    SupervisorObservationStats,
)


class SqlAlchemySupervisorObservationRepository:
    """提供数据持久化访问能力。"""
    def __init__(self, session: AsyncSession) -> None:
        """初始化当前对象。"""
        self.session = session

    async def add(
        self,
        observation: SupervisorFailureObservation,
    ) -> None:
        """添加一个集合元素。"""
        advice = observation.advice
        model = SupervisorFailureObservationModel(
            literature_run_id=observation.literature_run_id,
            failure_step=observation.failure.step.value,
            failure_category=observation.failure.category.value,
            failure_message=observation.failure.message,
            failure_retryable=observation.failure.retryable,
            failure_attempt=observation.failure.attempt,
            failure_error_type=observation.failure.error_type,
            rule_disposition=observation.rule_disposition.value,
            jev_disposition=(
                advice.disposition.value
                if advice is not None
                else None
            ),
            confidence=(
                advice.confidence if advice is not None else None
            ),
            retry_probability=(
                advice.probabilities[FailureDisposition.RETRY]
                if advice is not None
                else None
            ),
            stop_probability=(
                advice.probabilities[FailureDisposition.STOP]
                if advice is not None
                else None
            ),
            model=advice.model if advice is not None else None,
            request_id=(
                advice.request_id if advice is not None else None
            ),
            latency_ms=(
                advice.latency_ms if advice is not None else None
            ),
            agrees=observation.agrees,
            meets_confidence_threshold=(
                observation.meets_confidence_threshold
            ),
            error=observation.error,
        )
        self.session.add(model)
        await self.session.flush()

    async def get_stats(
        self,
        literature_run_id: int | None = None,
        *,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> SupervisorObservationStats:
        """获取对应记录。"""
        model = SupervisorFailureObservationModel
        successful = model.jev_disposition.is_not(None)
        agreement = model.agrees.is_(True)
        disagreement = model.agrees.is_(False)
        high_confidence = model.meets_confidence_threshold.is_(True)
        high_confidence_disagreement = (
            high_confidence & disagreement
        )
        retry_advice = (
            model.jev_disposition == FailureDisposition.RETRY.value
        )
        stop_advice = (
            model.jev_disposition == FailureDisposition.STOP.value
        )

        aggregates = (
            func.count(model.id),
            _count_when(successful),
            _count_when(agreement),
            _count_when(disagreement),
            _count_when(high_confidence),
            _count_when(high_confidence_disagreement),
            _count_when(retry_advice),
            _count_when(stop_advice),
            func.avg(model.confidence),
            func.avg(model.latency_ms),
        )

        summary_statement = select(*aggregates)
        category_statement = (
            select(model.failure_category, *aggregates)
            .group_by(model.failure_category)
            .order_by(model.failure_category)
        )
        filters = _observation_filters(
            literature_run_id=literature_run_id,
            created_from=created_from,
            created_to=created_to,
        )
        if filters:
            summary_statement = summary_statement.where(*filters)
            category_statement = category_statement.where(*filters)

        summary_result = await self.session.execute(
            summary_statement
        )
        summary = _aggregate_values(summary_result.one())

        category_result = await self.session.execute(
            category_statement
        )
        categories = [
            _category_stats(row)
            for row in category_result.all()
        ]

        return SupervisorObservationStats.model_validate(
            {
                "literature_run_id": literature_run_id,
                **summary,
                "by_failure_category": categories,
            }
        )

    async def list_observations(
        self,
        query: SupervisorObservationListQuery,
    ) -> list[SupervisorFailureObservationRecord]:
        """列出符合条件的记录。"""
        model = SupervisorFailureObservationModel
        filters = _observation_filters(
            literature_run_id=query.literature_run_id,
            created_from=query.created_from,
            created_to=query.created_to,
        )
        if query.failure_category is not None:
            filters.append(
                model.failure_category
                == query.failure_category.value
            )
        if query.agrees is not None:
            filters.append(model.agrees.is_(query.agrees))
        if query.min_confidence is not None:
            filters.append(
                model.confidence >= query.min_confidence
            )

        statement = (
            select(model)
            .where(*filters)
            .order_by(model.created_at.desc(), model.id.desc())
            .limit(query.limit)
            .offset(query.offset)
        )
        result = await self.session.execute(statement)
        return [
            _to_record(item)
            for item in result.scalars().all()
        ]


def _count_when(condition: ColumnElement[bool]):
    return func.coalesce(
        func.sum(case((condition, 1), else_=0)),
        0,
    )


def _aggregate_values(
    row: Row[Any] | Sequence[object],
) -> dict[str, object]:
    (
        total,
        successes,
        agreements,
        disagreements,
        high_confidence,
        high_confidence_disagreements,
        retries,
        stops,
        average_confidence,
        average_latency_ms,
    ) = row
    total_count = int(str(total))
    success_count = int(str(successes))
    agreement_count = int(str(agreements))
    disagreement_count = int(str(disagreements))
    high_confidence_count = int(str(high_confidence))
    high_confidence_disagreement_count = int(
        str(high_confidence_disagreements)
    )

    return {
        "total_count": total_count,
        "advice_success_count": success_count,
        "advice_error_count": total_count - success_count,
        "agreement_count": agreement_count,
        "disagreement_count": disagreement_count,
        "high_confidence_count": high_confidence_count,
        "high_confidence_disagreement_count": (
            high_confidence_disagreement_count
        ),
        "retry_advice_count": int(str(retries)),
        "stop_advice_count": int(str(stops)),
        "advice_success_rate": _ratio(success_count, total_count),
        "agreement_rate": _ratio(
            agreement_count,
            success_count,
        ),
        "high_confidence_disagreement_rate": _ratio(
            high_confidence_disagreement_count,
            high_confidence_count,
        ),
        "average_confidence": _optional_float(average_confidence),
        "average_latency_ms": _optional_float(average_latency_ms),
    }


def _category_stats(
    row: Row[Any] | Sequence[object],
) -> SupervisorFailureCategoryStats:
    category, *aggregate_row = row
    return SupervisorFailureCategoryStats.model_validate(
        {
            "category": category,
            **_aggregate_values(aggregate_row),
        }
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _optional_float(value: object) -> float | None:
    return round(float(str(value)), 4) if value is not None else None


def _observation_filters(
    *,
    literature_run_id: int | None,
    created_from: datetime | None,
    created_to: datetime | None,
) -> list[ColumnElement[bool]]:
    model = SupervisorFailureObservationModel
    filters: list[ColumnElement[bool]] = []
    if literature_run_id is not None:
        filters.append(model.literature_run_id == literature_run_id)
    if created_from is not None:
        filters.append(model.created_at >= created_from)
    if created_to is not None:
        filters.append(model.created_at <= created_to)
    return filters


def _to_record(
    model: SupervisorFailureObservationModel,
) -> SupervisorFailureObservationRecord:
    advice: dict[str, object] | None = None
    if model.jev_disposition is not None:
        advice = {
            "disposition": model.jev_disposition,
            "confidence": model.confidence,
            "probabilities": {
                FailureDisposition.RETRY: model.retry_probability,
                FailureDisposition.STOP: model.stop_probability,
            },
            "model": model.model,
            "request_id": model.request_id,
            "latency_ms": model.latency_ms,
        }

    return SupervisorFailureObservationRecord.model_validate(
        {
            "id": model.id,
            "literature_run_id": model.literature_run_id,
            "failure": {
                "step": model.failure_step,
                "category": model.failure_category,
                "message": model.failure_message,
                "retryable": model.failure_retryable,
                "attempt": model.failure_attempt,
                "error_type": model.failure_error_type,
            },
            "rule_disposition": model.rule_disposition,
            "advice": advice,
            "agrees": model.agrees,
            "meets_confidence_threshold": (
                model.meets_confidence_threshold
            ),
            "error": model.error,
            "created_at": model.created_at,
        }
    )
