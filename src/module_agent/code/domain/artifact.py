from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field, HttpUrl, StringConstraints, model_validator

from module_agent.code.domain.repository import RepositoryEvidence


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1),
]
CommitSha = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-fA-F]{7,64}$"),
]




class CodeArtifactOrigin(StrEnum):
    """封装 CodeArtifactOrigin 相关的数据和行为。"""
    OFFICIAL = "official"
    AUTHOR = "author"
    THIRD_PARTY = "third_party"
    REPRODUCTION_PLAN = "reproduction_plan"
    UNKNOWN = "unknown"


class CodeArtifactStatus(StrEnum):
    """定义可用的状态值。"""
    REPOSITORY_READY = "repository_ready"
    REPRODUCTION_PLANNED = "reproduction_planned"
    FAILED = "failed"


class CodeAvailabilityStatus(StrEnum):
    """论文对应代码的公开和许可状态。"""

    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    SOURCE_AVAILABLE = "source_available"
    OPEN_SOURCE = "open_source"


class RepositoryAnalysis(BaseModel):
    """对已获取仓库进行静态分析得到的结构化摘要。"""

    dependency_files: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    entrypoints: list[str] = Field(default_factory=list)
    module_candidates: list[str] = Field(default_factory=list)
    dataset_references: list[str] = Field(default_factory=list)
    weight_references: list[str] = Field(default_factory=list)
    requirement_matches: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ReproductionScaffold(BaseModel):
    """根据复现计划生成的最小可运行工程骨架。"""

    local_path: NonEmptyText
    files: Annotated[list[NonEmptyText], Field(min_length=1)]


class GeneratedImplementation(BaseModel):
    """LLM-generated candidate implementation, still requiring validation."""

    algorithm_py: Annotated[str, Field(min_length=1, max_length=100_000)]
    test_algorithm_py: Annotated[str, Field(min_length=1, max_length=100_000)]
    dependencies: Annotated[list[str], Field(max_length=30)] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)


class ReproductionPlan(BaseModel):
    """封装 ReproductionPlan 相关的数据和行为。"""
    # 论文希望解决的研究问题。
    research_problem: NonEmptyText
    # 复现方法的建议步骤。
    implementation_steps: Annotated[list[NonEmptyText], Field(min_length=1)]
    # 方法所需的输入。
    inputs: list[str] = Field(default_factory=list)
    # 方法产生的输出。
    outputs: list[str] = Field(default_factory=list)
    # 复现时建议使用的依赖。
    suggested_dependencies: list[str] = Field(default_factory=list)
    # 复现前仍需确认的问题。
    open_questions: list[str] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)


class RepositoryCheckout(BaseModel):
    """封装 RepositoryCheckout 相关的数据和行为。"""
    # 代码仓库地址。
    repository_url: HttpUrl
    # 固定后的 Git 提交 SHA。
    commit_sha: CommitSha
    # 产物在本机工作区中的路径。
    local_path: NonEmptyText


class CodeArtifact(BaseModel):
    """封装 CodeArtifact 相关的数据和行为。"""
    # 关联的论文 ID。
    paper_id: Annotated[int, Field(gt=0)]
    # 代码产物或仓库的来源。
    origin: CodeArtifactOrigin
    # 当前处理状态。
    status: CodeArtifactStatus

    # 代码仓库地址。
    repository_url: HttpUrl | None = None
    # 固定后的 Git 提交 SHA。
    commit_sha: CommitSha | None = None
    # 仓库默认分支。
    default_branch: str | None = None
    # 仓库许可证的 SPDX 标识。
    license_spdx: str | None = None
    # 产物在本机工作区中的路径。
    local_path: str | None = None

    # 当前结果的可信度。
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.0
    # 支撑判断的证据列表。
    evidence: list[RepositoryEvidence] = Field(default_factory=list)
    # 不阻断流程的警告列表。
    warnings: list[str] = Field(default_factory=list)
    # 论文代码是否公开以及是否具有开源许可证。
    code_availability: CodeAvailabilityStatus = CodeAvailabilityStatus.UNKNOWN
    # 对已获取仓库的依赖、入口和数据要求分析。
    repository_analysis: RepositoryAnalysis | None = None
    # 当前产物包含的相对文件路径。
    file_manifest: list[str] = Field(default_factory=list)
    # 没有可信仓库时生成的复现计划。
    reproduction_plan: ReproductionPlan | None = None
    # 复现目录是否包含模型生成、尚未验证的候选实现。
    implementation_generated: bool = False
    # 失败时的错误信息。
    error: str | None = None

    @model_validator(mode="after")
    def validate_status_payload(self) -> "CodeArtifact":
        """校验输入和业务约束。"""
        if self.status is CodeArtifactStatus.REPOSITORY_READY:
            if self.origin is CodeArtifactOrigin.REPRODUCTION_PLAN:
                raise ValueError("A repository artifact cannot use reproduction_plan origin")
            if not self.repository_url or not self.commit_sha or not self.local_path:
                raise ValueError(
                    "A ready repository requires repository_url, commit_sha, and local_path"
                )

        if self.status is CodeArtifactStatus.REPRODUCTION_PLANNED:
            if self.origin is not CodeArtifactOrigin.REPRODUCTION_PLAN:
                raise ValueError(
                    "A reproduction plan must use reproduction_plan origin"
                )
            if self.reproduction_plan is None:
                raise ValueError(
                    "A reproduction_planned artifact requires a reproduction plan"
                )

        if self.status is CodeArtifactStatus.FAILED and not self.error:
            raise ValueError("A failed artifact requires an error message")

        return self
