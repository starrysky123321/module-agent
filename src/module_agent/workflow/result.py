from module_agent.code.domain.artifact import CodeArtifact
from module_agent.code.domain.request import CodePaperInput
from module_agent.supervision.domain import WorkflowFailure
from module_agent.validation.domain import ValidationReport
from module_agent.workflow.domain import (
    SupervisorStep,
    WorkflowStatus,
)
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


PositiveAttempt = Annotated[int, Field(ge=1)]


class ModuleBuildResult(BaseModel):
    """表示一次处理结果。"""
    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 跨服务追踪 ID。
    trace_id: UUID | None = None
    # 当前处理状态。
    status: WorkflowStatus

    # 用户选中的论文 ID。
    selected_paper_ids: list[int] = Field(default_factory=list)
    # 筛选或确认后的论文列表。
    selected_papers: list[CodePaperInput] = Field(default_factory=list)
    # Code Agent 生成的产物列表。
    code_artifacts: list[CodeArtifact] = Field(default_factory=list)
    # Validation Agent 生成的报告列表。
    validation_reports: list[ValidationReport] = Field(
        default_factory=list
    )

    # 各阶段的执行次数。
    attempts: dict[SupervisorStep, PositiveAttempt] = Field(
        default_factory=dict
    )
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 工作流中的结构化失败。
    failure: WorkflowFailure | None = None
    
    
    @model_validator(mode="after")
    def validate_consistency(self) -> Self:
        """校验多个字段之间的一致性。"""
        if self.status not in {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        }:
            raise ValueError("Module build result must be terminal")

        if self.status is WorkflowStatus.COMPLETED:
            if self.failure is not None:
                raise ValueError("Completed result cannot contain failure")

            if not all(
                (
                    self.selected_paper_ids,
                    self.selected_papers,
                    self.code_artifacts,
                    self.validation_reports,
                )
            ):
                raise ValueError(
                    "Completed result requires papers, artifacts, and reports"
                )

            if len(self.selected_paper_ids) != len(
                set(self.selected_paper_ids)
            ):
                raise ValueError("Selected paper ids must be unique")

            selected_ids = set(self.selected_paper_ids)
            paper_ids = {paper.paper_id for paper in self.selected_papers}
            artifact_ids = {
                artifact.paper_id
                for artifact in self.code_artifacts
            }
            report_ids = {
                report.paper_id
                for report in self.validation_reports
            }
            
            if not (
                selected_ids
                == paper_ids
                == artifact_ids
                == report_ids
            ):
                raise ValueError(
                    "Completed result paper ids do not match"
                )

            if any(
                report.literature_run_id != self.literature_run_id
                for report in self.validation_reports
            ):
                raise ValueError(
                    "Validation report literature run id does not "
                    "match result"
                )

        if self.status is WorkflowStatus.FAILED:
            if self.failure is None:
                raise ValueError("Failed result must contain failure")

            if self.failure.retryable:
                raise ValueError("Final failure cannot be retryable")

            if (
                self.attempts.get(self.failure.step)
                != self.failure.attempt
            ):
                raise ValueError(
                    "Failure attempt does not match recorded attempts"
                )

        if self.status is WorkflowStatus.CANCELLED:
            if self.failure is not None:
                raise ValueError(
                    "Cancelled result cannot contain a failure"
                )

        return self
