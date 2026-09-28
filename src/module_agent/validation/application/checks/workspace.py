from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.ports import WorkspaceInspector
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)


class WorkspaceCheck:
    """封装 WorkspaceCheck 相关的数据和行为。"""
    def __init__(self, inspector: WorkspaceInspector) -> None:
        """初始化当前对象。"""
        self.inspector = inspector
        
    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.WORKSPACE
    
    def supports(self, artifact: CodeArtifact) -> bool:
        """判断当前检查器是否支持该产物。"""
        return artifact.status is CodeArtifactStatus.REPOSITORY_READY

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        """执行当前任务。"""
        if artifact.local_path is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository artifact has no local path",
            )
        path = Path(artifact.local_path)
        if not self.inspector.is_directory(path):
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository workspace does not exist",
                details={"path": str(path)},
            )
        
        
        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary="Repository workspace exists",
            details={"path": str(path)},
        )
