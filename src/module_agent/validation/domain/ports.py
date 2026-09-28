from typing import Protocol
from pathlib import Path
from collections.abc import Sequence

from module_agent.code.domain.artifact import CodeArtifact
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
)
from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)


class StaticCheck(Protocol):
    """One read-only validation rule for a CodeArtifact."""

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前静态检查的类型。"""
        ...

    def supports(self, artifact: CodeArtifact) -> bool:
        """判断当前检查是否适用于该代码产物。"""
        ...

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        """执行只读检查并返回结构化结果。"""
        ...


class WorkspaceInspector(Protocol):
    """封装 WorkspaceInspector 相关的数据和行为。"""
    def is_directory(self, path: Path) -> bool:
        """判断路径是否为目录。"""
        ...


class GitInspector(Protocol):
    """封装 GitInspector 相关的数据和行为。"""
    async def head_commit(self, path: Path) -> str | None:
        """读取仓库当前提交 SHA。"""
        ...
        

class RepositoryFileInspector(Protocol):
    """封装 RepositoryFileInspector 相关的数据和行为。"""
    def list_root_files(self, repository: Path) -> Sequence[str]:
        """列出仓库根目录文件。"""
        ...
        
    
class SandboxRunner(Protocol):
    """封装 SandboxRunner 相关的数据和行为。"""
    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        """执行当前用例。"""
        ...
