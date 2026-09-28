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


class LicenseCheck:
    """封装 LicenseCheck 相关的数据和行为。"""
    LICENSE_NAMES = frozenset(
        {
            "license",
            "license.md",
            "license.txt",
            "copying",
            "copying.md",
            "copying.txt",
        }
    )

    def __init__(self, inspector: RepositoryFileInspector) -> None:
        """初始化当前对象。"""
        self.inspector = inspector

    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.LICENSE

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
        matched_file = next(
            (
                filename
                for filename in files
                if filename.casefold() in self.LICENSE_NAMES
            ),
            None,
        )
        license_spdx = self._known_spdx(artifact.license_spdx)

        if matched_file is not None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.PASSED,
                summary="Repository license file found",
                details={
                    "file": matched_file,
                    "license_spdx": license_spdx,
                    "source": "repository_file",
                },
            )

        if license_spdx is not None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.PASSED,
                summary="Repository license found in artifact metadata",
                details={
                    "license_spdx": license_spdx,
                    "source": "artifact_metadata",
                },
            )

        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.WARNING,
            summary="Repository license could not be identified",
        )

    @staticmethod
    def _known_spdx(value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized or normalized.casefold() == "noassertion":
            return None
        return normalized
