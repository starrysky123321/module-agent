import asyncio

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.application.static_validator import (
    StaticValidator,
)
from module_agent.validation.domain import (
    SandboxExecutionResult,
    SandboxValidationOptions,
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationPolicy,
    ValidationRequest,
    ValidationStatus,
)


class PassingArtifactCheck:
    @property
    def kind(self) -> ValidationCheckKind:
        return ValidationCheckKind.ARTIFACT_CONTRACT

    def supports(self, artifact: CodeArtifact) -> bool:
        return True

    async def run(self, artifact: CodeArtifact) -> ValidationCheck:
        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary=f"Artifact {artifact.paper_id} is valid",
        )


class FakeSandboxRunner:
    def __init__(self) -> None:
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        argv = request.argv
        if "checked={len(files)}" in argv[2]:
            stdout = "checked=1\n"
        elif "imported=" in argv[2]:
            stdout = "imported=1\nfailed=0\n"
        else:
            stdout = "smoke passed\n"
        return SandboxExecutionResult(
            exit_code=0,
            stdout=stdout,
            duration_ms=5,
        )


def repository_artifact(paper_id: int = 1) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/example/project",
        commit_sha="abcdef1",
        local_path=f"/workspace/{paper_id}",
    )


def reproduction_artifact(paper_id: int = 2) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Reproduce the method",
            implementation_steps=["Implement it"],
        ),
    )


def agent(*, sandbox_runner=None) -> ValidationAgent:
    return ValidationAgent(
        StaticValidator([PassingArtifactCheck()]),
        sandbox_runner=sandbox_runner,
    )


def test_agent_returns_one_ordered_report_per_artifact() -> None:
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[repository_artifact(1), reproduction_artifact(2)],
    )

    reports = asyncio.run(agent().run(request))

    assert [report.paper_id for report in reports] == [1, 2]
    assert reports[0].status is ValidationStatus.PASSED
    assert reports[1].status is ValidationStatus.PARTIAL
    assert all(report.code_executed is False for report in reports)


def test_agent_runs_only_explicit_sandbox_checks() -> None:
    runner = FakeSandboxRunner()
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[repository_artifact()],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
        sandbox_options=SandboxValidationOptions(
            import_modules=["package"],
            smoke_test_argv=["python", "-m", "package", "--help"],
        ),
    )

    report = asyncio.run(agent(sandbox_runner=runner).run(request))[0]

    assert report.status is ValidationStatus.PASSED
    assert report.code_executed is True
    assert [check.kind for check in report.checks] == [
        ValidationCheckKind.ARTIFACT_CONTRACT,
        ValidationCheckKind.SYNTAX,
        ValidationCheckKind.IMPORT,
        ValidationCheckKind.SMOKE_TEST,
    ]
    assert len(runner.requests) == 3


def test_agent_reports_missing_sandbox_configuration_per_artifact() -> None:
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[repository_artifact(1), repository_artifact(2)],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
    )

    reports = asyncio.run(agent().run(request))

    assert len(reports) == 2
    assert all(report.status is ValidationStatus.FAILED for report in reports)
    assert all("no sandbox runner" in (report.error or "") for report in reports)


def test_agent_does_not_sandbox_reproduction_plans() -> None:
    runner = FakeSandboxRunner()
    request = ValidationRequest(
        literature_run_id=7,
        artifacts=[reproduction_artifact()],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
    )

    report = asyncio.run(agent(sandbox_runner=runner).run(request))[0]

    assert report.status is ValidationStatus.PARTIAL
    assert report.code_executed is False
    assert runner.requests == []
