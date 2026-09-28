from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.ports import GitInspector
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)
from pathlib import Path



class GitCommitCheck:
    """封装 GitCommitCheck 相关的数据和行为。"""
    def __init__(self, inspector: GitInspector) -> None:
        """初始化当前对象。"""
        self.inspector = inspector

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.GIT_COMMIT

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
                details={"path": artifact.local_path},
            )
            
        if artifact.commit_sha is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository artifact has no commit SHA",
                details={"path": artifact.local_path},
            )
        
        head_commit = await self.inspector.head_commit(Path(artifact.local_path))
        
        
        if head_commit is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Unable to read repository HEAD commit",
                details={"path": artifact.local_path},
            )
        actual_commit = head_commit.strip().lower()
        expected_commit = artifact.commit_sha.strip().lower()
        
        if not actual_commit.startswith(expected_commit):
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository head commit does not match artifact commit SHA",
                details={"path": artifact.local_path, "expected_commit": expected_commit, "actual_commit": actual_commit},
            )
        
        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary="Repository head commit matches artifact commit SHA",
            details={"path": artifact.local_path, "expected_commit": expected_commit, "actual_commit": actual_commit},
        )
