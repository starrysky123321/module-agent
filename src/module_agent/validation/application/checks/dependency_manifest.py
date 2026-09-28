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


class DependencyManifestCheck:
    """封装 DependencyManifestCheck 相关的数据和行为。"""
    MANIFEST_NAMES = frozenset(
        {
            "build.gradle",
            "build.gradle.kts",
            "cargo.toml",
            "cmakelists.txt",
            "conda.yaml",
            "conda.yml",
            "conanfile.py",
            "conanfile.txt",
            "description",
            "environment.yaml",
            "environment.yml",
            "go.mod",
            "package.json",
            "pipfile",
            "poetry.lock",
            "pom.xml",
            "pyproject.toml",
            "renv.lock",
            "requirements.txt",
            "setup.cfg",
            "setup.py",
            "uv.lock",
            "vcpkg.json",
        }
    )

    def __init__(self, inspector: RepositoryFileInspector) -> None:
        """初始化当前对象。"""
        self.inspector = inspector

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.DEPENDENCY_MANIFEST

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
        matched_files = sorted(
            (
                filename
                for filename in files
                if self._is_manifest(filename)
            ),
            key=str.casefold,
        )

        if not matched_files:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.WARNING,
                summary="Repository has no recognized dependency manifest",
            )

        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary="Repository dependency manifest found",
            details={"files": matched_files},
        )

    @classmethod
    def _is_manifest(cls, filename: str) -> bool:
        normalized = filename.casefold()
        return normalized in cls.MANIFEST_NAMES or (
            normalized.startswith("requirements-")
            and normalized.endswith(".txt")
        )
