from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.ports import RepositoryFileInspector
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)

class ReadmeCheck:
    """封装 ReadmeCheck 相关的数据和行为。"""
    def __init__(self, inspector: RepositoryFileInspector) -> None:
        """初始化当前对象。"""
        self.inspector = inspector

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.README

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
        
        files = self.inspector.list_root_files(Path(artifact.local_path))
        readme_names = {
            "readme",
            "readme.md",
            "readme.rst",
            "readme.txt",
        }
        
        matched_file = next(
            (
                filename
                for filename in files
                if filename.casefold() in readme_names
            ),
            None,
        )
        
        if matched_file is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.WARNING,
                summary="Repository has no README file",
            )
        
        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary="Repository README file found",
            details={"file": matched_file},
        )
