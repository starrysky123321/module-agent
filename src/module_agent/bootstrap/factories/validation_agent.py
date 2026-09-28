from pathlib import Path

from module_agent.validation.adapters.docker import DockerSandboxRunner
from module_agent.validation.adapters.files import (
    LocalRepositoryFileInspector,
)
from module_agent.validation.adapters.git import LocalGitInspector
from module_agent.validation.adapters.workspace import (
    LocalWorkspaceInspector,
)
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.application.checks.dependency_manifest import (
    DependencyManifestCheck,
)
from module_agent.validation.application.checks.git_commit import (
    GitCommitCheck,
)
from module_agent.validation.application.checks.license import LicenseCheck
from module_agent.validation.application.checks.readme import ReadmeCheck
from module_agent.validation.application.checks.reproduction_plan import (
    ReproductionPlanCheck,
)
from module_agent.validation.application.checks.workspace import (
    WorkspaceCheck,
)
from module_agent.validation.application.static_validator import (
    StaticValidator,
)


def build_validation_agent(
    *,
    workspace_root: Path,
    sandbox_image: str | None = None,
    git_timeout_seconds: float = 10.0,
) -> ValidationAgent:
    """Wire validation use cases to local and optional Docker adapters."""
    workspace = LocalWorkspaceInspector(workspace_root)
    git = LocalGitInspector(
        workspace_root,
        timeout_seconds=git_timeout_seconds,
    )
    files = LocalRepositoryFileInspector(workspace_root)
    static_validator = StaticValidator(
        [
            WorkspaceCheck(workspace),
            GitCommitCheck(git),
            ReadmeCheck(files),
            LicenseCheck(files),
            DependencyManifestCheck(files),
            ReproductionPlanCheck(),
        ]
    )
    normalized_image = (sandbox_image or "").strip()
    sandbox_runner = (
        DockerSandboxRunner(
            workspace_root,
            image=normalized_image,
        )
        if normalized_image
        else None
    )

    return ValidationAgent(
        static_validator,
        sandbox_runner=sandbox_runner,
    )
