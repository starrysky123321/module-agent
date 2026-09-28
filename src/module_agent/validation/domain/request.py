from enum import StrEnum
from typing import Annotated
import keyword
from pathlib import PurePosixPath

from pydantic import BaseModel, Field, field_validator, model_validator

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.code.domain.jobs import ComputeTarget


class ValidationMode(StrEnum):
    """How deeply an artifact may be inspected."""

    STATIC = "static"
    SANDBOX = "sandbox"


class ValidationPolicy(BaseModel):
    """Safety limits applied to one Validation Agent run."""

    # 验证执行模式。
    mode: ValidationMode = ValidationMode.STATIC
    # 沙箱是否允许访问网络。
    allow_network: bool = False
    # 操作超时时间，单位为秒。
    timeout_seconds: Annotated[int, Field(gt=0, le=900)] = 60
    # 沙箱内存上限，单位为 MiB。
    memory_limit_mb: Annotated[int, Field(ge=128, le=16384)] = 1024
    # 沙箱可使用的 CPU 上限。
    cpu_limit: Annotated[float, Field(gt=0.0, le=8.0)] = 1.0
    # 沙箱需要的计算资源；GPU 必须由 GPU 节点提供。
    compute_target: ComputeTarget = ComputeTarget.CPU

    @model_validator(mode="after")
    def reject_network_for_static_validation(self) -> "ValidationPolicy":
        """拒绝不符合约束的输入。"""
        if self.mode is ValidationMode.STATIC and self.allow_network:
            raise ValueError("Static validation cannot enable network access")
        return self


class SandboxValidationOptions(BaseModel):
    """封装 SandboxValidationOptions 相关的数据和行为。"""
    # 需要验证导入的 Python 模块。
    import_modules: Annotated[
        list[str],
        Field(max_length=20),
    ] = Field(default_factory=list)

    # 冒烟测试的参数列表。
    smoke_test_argv: (
        Annotated[list[str], Field(min_length=1, max_length=64)]
        | None
    ) = None

    # 冒烟测试的工作目录。
    smoke_test_working_directory: str = "."
    # 在一次性沙箱虚拟环境中安装仓库依赖。
    install_dependencies: bool = False
    # 依赖安装成功后运行仓库的完整 pytest 测试。
    run_project_tests: bool = False
    
    
    @field_validator("import_modules")
    @classmethod
    def validate_import_modules(cls, value: list[str]) -> list[str]:
        """校验输入和业务约束。"""
        normalized = [module.strip() for module in value]

        for module in normalized:
            parts = module.split(".")
            if (
                not module
                or any(
                    not part.isidentifier() or keyword.iskeyword(part)
                    for part in parts
                )
            ):
                raise ValueError(
                    f"Invalid Python import module: {module!r}"
                )

        if len(normalized) != len(set(normalized)):
            raise ValueError("Import modules must be unique")

        return normalized
    
    
    @field_validator("smoke_test_argv")
    @classmethod
    def validate_smoke_test_argv(
        cls,
        value: list[str] | None,
    ) -> list[str] | None:
        """校验输入和业务约束。"""
        if value is None:
            return None

        if not value[0].strip():
            raise ValueError("Smoke test executable must be non-empty")

        if any("\x00" in argument for argument in value):
            raise ValueError(
                "Smoke test arguments cannot contain null bytes"
            )

        return value
    
    @field_validator("smoke_test_working_directory")
    @classmethod
    def validate_smoke_test_working_directory(
        cls,
        value: str,
    ) -> str:
        """校验输入和业务约束。"""
        if "\x00" in value:
            raise ValueError(
                "Smoke test working directory cannot contain null bytes"
            )

        path = PurePosixPath(value)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "Smoke test working directory must stay inside repository"
            )

        return str(path)
    
    
    @model_validator(mode="after")
    def validate_smoke_test_configuration(
        self,
    ) -> "SandboxValidationOptions":
        """校验输入和业务约束。"""
        if (
            self.smoke_test_argv is None
            and self.smoke_test_working_directory != "."
        ):
            raise ValueError(
                "Smoke test working directory requires smoke_test_argv"
            )

        if self.run_project_tests and not self.install_dependencies:
            raise ValueError(
                "Project tests require dependency installation"
            )
        return self
    


class ValidationRequest(BaseModel):
    """Stable input contract passed from Workflow to Validation Agent."""

    # 关联的文献任务 ID。
    literature_run_id: Annotated[int, Field(gt=0)]
    # 等待处理的代码产物。
    artifacts: Annotated[list[CodeArtifact], Field(min_length=1, max_length=20)]
    # 本次验证使用的安全策略。
    policy: ValidationPolicy = Field(default_factory=ValidationPolicy)
    # 受控沙箱的运行参数。
    sandbox_options: SandboxValidationOptions | None = None
    # 用户提出的验收要求。
    user_requirements: Annotated[str, Field(max_length=5000)] | None = None
    
    @field_validator("user_requirements", mode="before")
    @classmethod
    def normalize_user_requirements(cls, value: object) -> object:
        """规范化输入数据。"""
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        return value

    @model_validator(mode="after")
    def reject_duplicate_artifacts(self) -> "ValidationRequest":
        """拒绝不符合约束的输入。"""
        paper_ids = [artifact.paper_id for artifact in self.artifacts]
        if len(paper_ids) != len(set(paper_ids)):
            raise ValueError("Validation artifacts must have unique paper ids")
        return self
    
        
    @model_validator(mode="after")
    def reject_sandbox_options_in_static_mode(
        self,
    ) -> "ValidationRequest":
        """拒绝不符合约束的输入。"""
        if (
            self.policy.mode is ValidationMode.STATIC
            and self.sandbox_options is not None
        ):
            raise ValueError(
                "Static validation cannot include sandbox options"
            )

        if (
            self.sandbox_options is not None
            and self.sandbox_options.install_dependencies
            and not self.policy.allow_network
        ):
            raise ValueError(
                "Dependency installation requires sandbox network access"
            )

        return self
