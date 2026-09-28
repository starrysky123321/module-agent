from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from module_agent.supervision.domain.failure import (
    WorkflowFailureCategory,
)


class SupervisorObservationStatsQuery(BaseModel):
    """封装 SupervisorObservationStatsQuery 相关的数据和行为。"""
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)] | None = None
    # 观察记录创建时间下界。
    created_from: datetime | None = None
    # 观察记录创建时间上界。
    created_to: datetime | None = None

    @field_validator("created_from", "created_to")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        """要求时间字段包含时区。"""
        if value is not None and value.tzinfo is None:
            raise ValueError("Observation timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """校验数值是否处于合法范围。"""
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise ValueError("created_from cannot be after created_to")
        return self


class SupervisorObservationListQuery(
    SupervisorObservationStatsQuery
):
    """封装 SupervisorObservationListQuery 相关的数据和行为。"""
    # 失败所属的类别。
    failure_category: WorkflowFailureCategory | None = None
    # Jev 建议是否与规则决策一致。
    agrees: bool | None = None
    # 查询允许的最低可信度。
    min_confidence: Annotated[
        float,
        Field(ge=0.0, le=1.0),
    ] | None = None
    # 单次查询返回数量上限。
    limit: Annotated[int, Field(ge=1, le=200)] = 50
    # 分页查询偏移量。
    offset: Annotated[int, Field(ge=0)] = 0
