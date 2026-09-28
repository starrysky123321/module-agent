from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, StringConstraints, model_validator

from module_agent.workflow.domain import (
    SupervisorStep,
    WorkflowStatus,
)


DecisionReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=500,
    ),
]


class SupervisorAction(StrEnum):
    """封装 SupervisorAction 相关的数据和行为。"""
    ROUTE = "route"
    WAIT = "wait"
    RETRY = "retry"
    FINISH = "finish"
    FAIL = "fail"
    CANCEL = "cancel"
    
    
class SupervisorDecision(BaseModel):
    """表示一次调度决策。"""
    # Supervisor 建议采取的动作。
    action: SupervisorAction
    # Supervisor 决定的下一步。
    next_step: SupervisorStep
    # 当前处理状态。
    status: WorkflowStatus
    # 生成当前结果的原因。
    reason: DecisionReason

    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """校验多个字段之间的一致性。"""
        if self.action is SupervisorAction.FINISH:
            if (
                self.next_step is not SupervisorStep.FINISH
                or self.status is not WorkflowStatus.COMPLETED
            ):
                raise ValueError(
                    "FINISH action requires finish step and completed status"
                )

        elif self.action is SupervisorAction.FAIL:
            if (
                self.next_step is not SupervisorStep.FINISH
                or self.status is not WorkflowStatus.FAILED
            ):
                raise ValueError(
                    "FAIL action requires finish step and failed status"
                )

        elif self.action is SupervisorAction.CANCEL:
            if (
                self.next_step is not SupervisorStep.FINISH
                or self.status is not WorkflowStatus.CANCELLED
            ):
                raise ValueError(
                    "CANCEL action requires finish step and cancelled status"
                )

        elif self.action in {
            SupervisorAction.ROUTE,
            SupervisorAction.RETRY,
        }:
            if self.next_step is SupervisorStep.FINISH:
                raise ValueError(
                    "ROUTE and RETRY actions cannot target finish"
                )

            if self.status in {
                WorkflowStatus.COMPLETED,
                WorkflowStatus.FAILED,
                WorkflowStatus.CANCELLED,
            }:
                raise ValueError(
                    "ROUTE and RETRY actions cannot use a terminal status"
                )

        elif self.action is SupervisorAction.WAIT:
            expected_status = {
                SupervisorStep.LITERATURE: (
                    WorkflowStatus.SEARCHING_LITERATURE
                ),
                SupervisorStep.PAPER_SELECTION: (
                    WorkflowStatus.WAITING_FOR_PAPER_SELECTION
                ),
                SupervisorStep.CODE: WorkflowStatus.WAITING_FOR_CODE,
            }.get(self.next_step)

            if expected_status is None:
                raise ValueError(
                    "WAIT action only supports literature, paper selection, "
                    "or code completion"
                )

            if self.status is not expected_status:
                raise ValueError(
                    "WAIT action status does not match its next step"
                )

        return self
