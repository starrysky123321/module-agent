from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from module_agent.code.domain.artifact import (
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.validation.domain.request import ValidationMode


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]


class ValidationStatus(StrEnum):
    """定义可用的状态值。"""
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"


class ValidationCheckStatus(StrEnum):
    """定义可用的状态值。"""
    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"
    SKIPPED = "skipped"


class ValidationCheckKind(StrEnum):
    """定义可用的分类值。"""
    ARTIFACT_CONTRACT = "artifact_contract"
    WORKSPACE = "workspace"
    GIT_COMMIT = "git_commit"
    README = "readme"
    LICENSE = "license"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    REPRODUCTION_PLAN = "reproduction_plan"
    SECURITY_SCAN = "security_scan"
    SYNTAX = "syntax"
    IMPORT = "import"
    SMOKE_TEST = "smoke_test"
    PROJECT_TESTS = "project_tests"
    DEPENDENCY_INSTALL = "dependency_install"


class ValidationCheck(BaseModel):
    """封装 ValidationCheck 相关的数据和行为。"""
    # 检查或消息的类型。
    kind: ValidationCheckKind
    # 当前处理状态。
    status: ValidationCheckStatus
    # 检查结果摘要。
    summary: NonEmptyText
    # 检查结果的结构化详情。
    details: dict[str, object] = Field(default_factory=dict)
    # 检查时执行的受控命令。
    command: str | None = None
    # 受控命令的退出码。
    exit_code: int | None = None
    # 操作耗时，单位为毫秒。
    duration_ms: Annotated[int | None, Field(ge=0)] = None


class ValidationReport(BaseModel):
    """Machine-readable validation result for one CodeArtifact."""

    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 关联的论文 ID。
    paper_id: Annotated[int, Field(gt=0)]
    # 被检查代码产物的来源。
    artifact_origin: CodeArtifactOrigin
    # 被检查代码产物的状态。
    artifact_status: CodeArtifactStatus
    # 验证执行模式。
    mode: ValidationMode
    # 当前处理状态。
    status: ValidationStatus
    # 本次验证包含的检查结果。
    checks: Annotated[list[ValidationCheck], Field(min_length=1)]
    # 验证期间是否执行过代码。
    code_executed: bool = False
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 失败时的错误信息。
    error: NonEmptyText | None = None

    @model_validator(mode="after")
    def validate_report_consistency(self) -> "ValidationReport":
        """校验验证报告内部字段是否一致。"""
        if self.mode is ValidationMode.STATIC and self.code_executed:
            raise ValueError("Static validation cannot execute artifact code")

        has_failed_check = any(
            check.status is ValidationCheckStatus.FAILED
            for check in self.checks
        )
        if self.status is ValidationStatus.PASSED:
            if has_failed_check or self.error is not None:
                raise ValueError(
                    "A passed validation cannot contain failures"
                )

        if (
            self.status is ValidationStatus.FAILED
            and not has_failed_check
            and self.error is None
        ):
            raise ValueError(
                "A failed validation requires a failed check or error"
            )

        return self
