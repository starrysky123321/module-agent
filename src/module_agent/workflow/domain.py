from enum import StrEnum
from typing import Any, TypedDict

from pydantic import BaseModel, Field, model_validator

from module_agent.literature.domain.search import SearchRequest
from module_agent.validation.domain.request import (
    SandboxValidationOptions,
    ValidationMode,
    ValidationPolicy,
)
from pydantic import field_validator
from module_agent.code.domain.jobs import ComputeTarget


class WorkflowStatus(StrEnum):
    """定义可用的状态值。"""
    CREATED = "created"
    SEARCHING_LITERATURE = "searching_literature"
    WAITING_FOR_PAPER_SELECTION = "waiting_for_paper_selection"
    PREPARING_CODE = "preparing_code"
    WAITING_FOR_CODE = "waiting_for_code"
    VALIDATING = "validating"
    COMPLETED = "completed"
    FAILED = "failed"
    CODE_READY = "code_ready"
    CANCELLED = "cancelled"


class SupervisorStep(StrEnum):
    """封装 SupervisorStep 相关的数据和行为。"""
    LITERATURE = "literature"
    PAPER_SELECTION = "paper_selection"
    CODE = "code"
    VALIDATION = "validation"
    FINISH = "finish"


class ModuleBuildRequest(BaseModel):
    """表示一次输入请求。"""
    # 用户提交的文献检索请求。
    literature_request: SearchRequest
    # 用户对代码产物的补充要求。
    code_requirements: str | None = None


class ModuleGraphState(TypedDict, total=False):
    """封装 ModuleGraphState 相关的数据和行为。"""
    # 本次处理的输入请求。
    request: dict[str, Any]
    # 当前处理状态。
    status: str
    # Supervisor 决定的下一步。
    next_step: str
    # Literature Agent 返回的阶段结果。
    literature: dict[str, Any]
    # 用户选中的论文 ID。
    selected_paper_ids: list[int]
    # 筛选或确认后的论文列表。
    selected_papers: list[dict[str, Any]]
    # 用户对代码产物的补充要求。
    code_requirements: str | None
    # Code Agent 生成的产物列表。
    code_artifacts: list[dict[str, Any]]
    # Validation Agent 生成的报告列表。
    validation_reports: list[dict[str, Any]]
    # Validation Agent 使用的执行策略。
    validation_policy: dict[str, Any]
    # 受控沙箱的运行参数。
    sandbox_options: dict[str, Any] | None
    # 用户对验证阶段的补充要求。
    validation_requirements: str | None
    # 工作流中的结构化失败。
    failure: dict[str, Any] | None
    # 失败时的错误信息。
    error: str
    # 关联的文献任务 ID。
    literature_run_id: int
    # 文献任务在消息队列中的消息 ID。
    literature_message_id: str
    # Supervisor 最近一次生成的决策。
    supervisor_decision: dict[str, Any]
    # 各阶段的执行次数。
    attempts: dict[str, int]
    # 跨服务追踪 ID。
    trace_id: str
    # 关联的 CodeRun ID。
    code_run_id: int
    # Code Worker 队列中的消息 ID。
    code_message_id: str
    # Code Agent 使用的资源池。
    compute_target: str
    # 关联的 ValidationRun ID。
    validation_run_id: int


class PaperSelectionRequest(BaseModel):
    """表示一次输入请求。"""
    # 用户选中的论文 ID。
    selected_paper_ids: list[int]
    # 用户对代码产物的补充要求。
    code_requirements: str | None = None
    
    @field_validator("selected_paper_ids")
    @classmethod
    def validate_paper_ids(cls, v: list[int]) -> list[int]:
        
        """校验输入和业务约束。"""
        if len(v) == 0:
            raise ValueError("Selected paper ids cannot be empty")
        if len(set(v)) != len(v):
            raise ValueError("Selected paper ids cannot be duplicate")  
        if any(id <= 0 for id in v):
            raise ValueError("Selected paper ids must be positive")
        return v

class PaperSelectionInterrupt(BaseModel):
    """封装 PaperSelectionInterrupt 相关的数据和行为。"""
    # 关联的文献任务 ID。
    literature_run_id: int = Field(gt=0)
    # 面向用户或日志的说明。
    message: str = "Please select papers before continuing"


class WorkflowValidationConfiguration(BaseModel):
    """封装 WorkflowValidationConfiguration 相关的数据和行为。"""
    # Validation Agent 使用的执行策略。
    validation_policy: ValidationPolicy = Field(
        default_factory=ValidationPolicy
    )
    # 受控沙箱的运行参数。
    sandbox_options: SandboxValidationOptions | None = None
    # 用户对验证阶段的补充要求。
    validation_requirements: str | None = None
    # Code Agent 使用 CPU 或 GPU worker 池。
    compute_target: ComputeTarget = ComputeTarget.CPU

    @model_validator(mode="after")
    def validate_sandbox_configuration(
        self,
    ) -> "WorkflowValidationConfiguration":
        """校验输入和业务约束。"""
        if (
            self.validation_policy.mode is ValidationMode.STATIC
            and self.sandbox_options is not None
        ):
            raise ValueError(
                "Static validation cannot include sandbox options"
            )
        return self


class PaperSelectionStartRequest(WorkflowValidationConfiguration):
    """表示一次输入请求。"""
    # 用户对代码产物的补充要求。
    code_requirements: str | None = None
    # 总工作流超时时间，单位为秒。
    workflow_timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86400,
    )


class ModuleWorkflowStartRequest(WorkflowValidationConfiguration):
    """表示一次输入请求。"""
    # 用户对代码产物的补充要求。
    code_requirements: str | None = None
    # 总工作流超时时间，单位为秒。
    workflow_timeout_seconds: int | None = Field(
        default=None,
        ge=1,
        le=86400,
    )
    
    
class LiteratureWaitInterrupt(BaseModel):
    """封装 LiteratureWaitInterrupt 相关的数据和行为。"""
    # 关联的文献任务 ID。
    literature_run_id: int = Field(gt=0)
    # 面向用户或日志的说明。
    message: str = "Waiting for literature search to complete"
    
class LiteratureCompletionSignal(BaseModel):
    """封装 LiteratureCompletionSignal 相关的数据和行为。"""
    # 关联的文献任务 ID。
    literature_run_id: int = Field(gt=0)


class CodeWaitInterrupt(BaseModel):
    """表示工作流正在等待独立 Code Worker。"""

    literature_run_id: int = Field(gt=0)
    message: str = "Waiting for Code Agent to complete"


class CodeCompletionSignal(BaseModel):
    """让 checkpoint 从 Code Worker 等待点继续。"""

    literature_run_id: int = Field(gt=0)
    code_run_id: int = Field(gt=0)
