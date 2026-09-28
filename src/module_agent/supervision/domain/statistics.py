from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from module_agent.supervision.domain.failure import (
    WorkflowFailureCategory,
)
from module_agent.supervision.domain.advice import (
    SupervisorFailureObservation,
)


Count = Annotated[int, Field(ge=0)]
Rate = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegativeFloat = Annotated[float, Field(ge=0.0)]


class SupervisorFailureCategoryStats(BaseModel):
    """封装 SupervisorFailureCategoryStats 相关的数据和行为。"""
    # 记录所属的业务分类。
    category: WorkflowFailureCategory
    # 观察记录总数。
    total_count: Count
    # 成功获得外部建议的次数。
    advice_success_count: Count
    # 外部建议调用失败的次数。
    advice_error_count: Count
    # 外部建议与规则一致的次数。
    agreement_count: Count
    # 外部建议与规则不一致的次数。
    disagreement_count: Count
    # 高可信建议的数量。
    high_confidence_count: Count
    # 高可信但与规则不一致的数量。
    high_confidence_disagreement_count: Count
    # 建议重试的次数。
    retry_advice_count: Count
    # 建议停止的次数。
    stop_advice_count: Count
    # 外部建议调用成功率。
    advice_success_rate: Rate | None = None
    # 外部建议与规则的一致率。
    agreement_rate: Rate | None = None
    # 高可信建议与规则的不一致率。
    high_confidence_disagreement_rate: Rate | None = None
    # 外部建议的平均可信度。
    average_confidence: Rate | None = None
    # 外部建议的平均耗时，单位为毫秒。
    average_latency_ms: NonNegativeFloat | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """校验统计数量之间的一致性。"""
        _validate_count_relationships(self)
        return self


class SupervisorObservationStats(BaseModel):
    """封装 SupervisorObservationStats 相关的数据和行为。"""
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)] | None = None
    # 观察记录总数。
    total_count: Count
    # 成功获得外部建议的次数。
    advice_success_count: Count
    # 外部建议调用失败的次数。
    advice_error_count: Count
    # 外部建议与规则一致的次数。
    agreement_count: Count
    # 外部建议与规则不一致的次数。
    disagreement_count: Count
    # 高可信建议的数量。
    high_confidence_count: Count
    # 高可信但与规则不一致的数量。
    high_confidence_disagreement_count: Count
    # 建议重试的次数。
    retry_advice_count: Count
    # 建议停止的次数。
    stop_advice_count: Count
    # 外部建议调用成功率。
    advice_success_rate: Rate | None = None
    # 外部建议与规则的一致率。
    agreement_rate: Rate | None = None
    # 高可信建议与规则的不一致率。
    high_confidence_disagreement_rate: Rate | None = None
    # 外部建议的平均可信度。
    average_confidence: Rate | None = None
    # 外部建议的平均耗时，单位为毫秒。
    average_latency_ms: NonNegativeFloat | None = None
    # 按失败类别分组的观察统计。
    by_failure_category: list[SupervisorFailureCategoryStats] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        """校验统计数量之间的一致性。"""
        _validate_count_relationships(self)
        if sum(item.total_count for item in self.by_failure_category) != (
            self.total_count
        ):
            raise ValueError(
                "Category totals must equal the observation total"
            )
        return self


class SupervisorFailureObservationRecord(
    SupervisorFailureObservation
):
    """封装 SupervisorFailureObservationRecord 相关的数据和行为。"""
    # 记录主键。
    id: Annotated[int, Field(gt=0)]
    # 记录创建时间。
    created_at: datetime


class SupervisorPolicyReadiness(BaseModel):
    """封装 SupervisorPolicyReadiness 相关的数据和行为。"""
    # 统计样本是否达到人工评审条件。
    eligible_for_review: bool
    # 观察样本量是否达到评审要求。
    sample_size_sufficient: bool
    # 外部建议调用成功率是否达标。
    call_reliability_sufficient: bool
    # 进入人工评审要求的最少观察数。
    minimum_observations: Annotated[int, Field(ge=1)]
    # 进入人工评审要求的最低调用成功率。
    minimum_success_rate: Rate
    # 基于统计结果生成的建议。
    recommendation: Literal[
        "collect_more_data",
        "investigate_call_failures",
        "review_high_confidence_disagreements",
    ]
    # Supervisor 观察统计。
    stats: SupervisorObservationStats


def _validate_count_relationships(
    value: SupervisorFailureCategoryStats | SupervisorObservationStats,
) -> None:
    if value.advice_success_count + value.advice_error_count != (
        value.total_count
    ):
        raise ValueError(
            "Advice success and error counts must equal total count"
        )
    if value.agreement_count + value.disagreement_count != (
        value.advice_success_count
    ):
        raise ValueError(
            "Agreement counts must equal successful advice count"
        )
    if value.high_confidence_disagreement_count > (
        value.high_confidence_count
    ):
        raise ValueError(
            "High-confidence disagreements cannot exceed "
            "high-confidence observations"
        )
    if value.retry_advice_count + value.stop_advice_count != (
        value.advice_success_count
    ):
        raise ValueError(
            "Retry and stop advice counts must equal successful advice count"
        )
