
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, Field, model_validator
from module_agent.supervision.domain.failure import WorkflowFailure



Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class FailureDisposition(StrEnum):
    """封装 FailureDisposition 相关的数据和行为。"""
    RETRY = "retry"
    STOP = "stop"


class SupervisorFailureAdvice(BaseModel):
    """封装 SupervisorFailureAdvice 相关的数据和行为。"""
    # 失败处置建议。
    disposition: FailureDisposition
    # 当前结果的可信度。
    confidence: Probability
    # 各处置建议的概率。
    probabilities: dict[FailureDisposition, Probability]

    # 调用的模型名称。
    model: str
    # 当前 HTTP 请求 ID。
    request_id: str | None = None
    # 外部建议调用耗时，单位为毫秒。
    latency_ms: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def validate_probabilities(self) -> Self:
        """校验概率分布是否合法。"""
        expected = set(FailureDisposition)
        actual = set(self.probabilities)

        if actual != expected:
            raise ValueError(
                "Failure advice probabilities must contain retry and stop"
            )

        return self


class SupervisorFailureObservation(BaseModel):
    """保存一次可观测记录。"""
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 工作流中的结构化失败。
    failure: WorkflowFailure

    # 规则策略给出的处置结果。
    rule_disposition: FailureDisposition
    # 外部决策器提供的建议。
    advice: SupervisorFailureAdvice | None = None

    # Jev 建议是否与规则决策一致。
    agrees: bool | None = None
    # 建议是否达到可信门槛。
    meets_confidence_threshold: bool | None = None
    # 失败时的错误信息。
    error: str | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """校验调用结果与错误字段是否一致。"""
        if self.advice is not None:
            if self.error is not None:
                raise ValueError(
                    "Successful observation cannot contain error"
                )

            if (
                self.agrees is None
                or self.meets_confidence_threshold is None
            ):
                raise ValueError(
                    "Successful observation requires comparison fields"
                )

        else:
            if not self.error:
                raise ValueError(
                    "Failed observation requires an error"
                )

            if (
                self.agrees is not None
                or self.meets_confidence_threshold is not None
            ):
                raise ValueError(
                    "Failed observation cannot contain comparison fields"
                )

        return self
