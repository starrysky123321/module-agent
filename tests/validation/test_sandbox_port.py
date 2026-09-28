import asyncio
from pathlib import Path

from module_agent.validation.domain.ports import SandboxRunner
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
)


class FakeSandboxRunner:
    def __init__(self) -> None:
        self.calls: list[SandboxExecutionRequest] = []

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        self.calls.append(request)
        return SandboxExecutionResult(
            exit_code=0,
            stdout="Python 3",
            duration_ms=5,
        )


def test_sandbox_runner_port_uses_domain_contracts() -> None:
    runner: SandboxRunner = FakeSandboxRunner()
    request = SandboxExecutionRequest(
        repository_path=Path("/workspace/repository"),
        argv=["python", "--version"],
        policy=ValidationPolicy(mode=ValidationMode.SANDBOX),
    )

    result = asyncio.run(runner.execute(request))

    assert runner.calls == [request]
    assert result.exit_code == 0
    assert result.stdout == "Python 3"
