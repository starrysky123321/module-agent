from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)


class SandboxExecutionRequest(BaseModel):
    """表示一次输入请求。"""
    # 待验证仓库的本地路径。
    repository_path: Path
    # 受控命令的参数列表。
    argv: Annotated[list[str], Field(min_length=1, max_length=64)]
    # 受控命令的工作目录。
    working_directory: str = "."
    # 本次验证使用的安全策略。
    policy: ValidationPolicy
    # 允许收集的最大输出字节数。
    max_output_bytes: Annotated[
        int,
        Field(ge=1024, le=1_048_576),
    ] = 65_536

    @field_validator("argv")
    @classmethod
    def validate_argv(cls, value: list[str]) -> list[str]:
        """校验输入和业务约束。"""
        if not value[0].strip():
            raise ValueError("Sandbox executable must be non-empty")

        if any("\x00" in argument for argument in value):
            raise ValueError("Sandbox arguments cannot contain null bytes")
        
        return value

    @field_validator("repository_path")
    @classmethod
    def require_absolute_repository_path(cls, value: Path) -> Path:
        """检查输入是否具备必要条件。"""
        if not value.is_absolute():
            raise ValueError("Repository path must be absolute")
        return value

    @field_validator("working_directory")
    @classmethod
    def validate_working_directory(cls, value: str) -> str:
        """校验输入和业务约束。"""
        path = PurePosixPath(value)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError(
                "Sandbox working directory must stay inside repository"
            )

        return str(path)
    
    @model_validator(mode="after")
    def require_sandbox_mode(self) -> "SandboxExecutionRequest":
        """检查输入是否具备必要条件。"""
        if self.policy.mode is not ValidationMode.SANDBOX:
            raise ValueError("Sandbox execution requires sandbox mode")
        return self

class SandboxExecutionResult(BaseModel):
    """表示一次处理结果。"""
    # 受控命令的退出码。
    exit_code: int | None = None
    # 受控命令的标准输出。
    stdout: str = ""
    # 受控命令的标准错误。
    stderr: str = ""
    # 操作耗时，单位为毫秒。
    duration_ms: Annotated[int, Field(ge=0)]
    # 受控命令是否超时。
    timed_out: bool = False
    # 命令输出是否被截断。
    output_truncated: bool = False

    @model_validator(mode="after")
    def validate_completion(self) -> "SandboxExecutionResult":
        """校验完成状态所需的字段。"""
        if not self.timed_out and self.exit_code is None:
            raise ValueError(
                "Completed sandbox execution requires an exit code"
            )
        return self
