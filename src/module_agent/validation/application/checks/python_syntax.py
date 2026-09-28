from pathlib import Path

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactStatus,
)
from module_agent.validation.domain.ports import SandboxRunner
from module_agent.validation.domain.report import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
)
from module_agent.validation.domain.request import (
    ValidationMode,
    ValidationPolicy,
)
from module_agent.validation.domain.sandbox import SandboxExecutionRequest



class PythonSyntaxCheck:
    
    """封装 PythonSyntaxCheck 相关的数据和行为。"""
    SYNTAX_SCRIPT = "\n".join(
        [
            "import pathlib",
            "import sys",
            "",
            "ignored = {",
            "    '.git',",
            "    '.venv',",
            "    'venv',",
            "    '__pycache__',",
            "    'build',",
            "    'dist',",
            "}",
            "",
            "files = sorted(",
            "    path",
            "    for path in pathlib.Path('.').rglob('*.py')",
            "    if not ignored.intersection(path.parts)",
            ")",
            "",
            "failures = 0",
            "for path in files:",
            "    try:",
            "        compile(",
            "            path.read_bytes(),",
            "            str(path),",
            "            'exec',",
            "            dont_inherit=True,",
            "        )",
            "    except (SyntaxError, ValueError) as exc:",
            "        failures += 1",
            "        print(f'{path}: {exc}', file=sys.stderr)",
            "",
            "print(f'checked={len(files)}')",
            "raise SystemExit(1 if failures else 0)",
        ]
    )
    
    def __init__(
        self,
        runner: SandboxRunner,
        policy: ValidationPolicy,
    ) -> None:
        """初始化当前对象。"""
        if policy.mode is not ValidationMode.SANDBOX:
            raise ValueError(
                "PythonSyntaxCheck requires sandbox validation mode"
            )

        self.runner = runner
        self.policy = policy


    @property
    def kind(self) -> ValidationCheckKind:
        """返回当前检查器的类型。"""
        return ValidationCheckKind.SYNTAX

    def supports(self, artifact: CodeArtifact) -> bool:
        """判断当前检查器是否支持该产物。"""
        return artifact.status in {
            CodeArtifactStatus.REPOSITORY_READY,
            CodeArtifactStatus.REPRODUCTION_PLANNED,
        }
    
    async def run(
        self,
        artifact: CodeArtifact,
    ) -> ValidationCheck:
        
        """执行当前任务。"""
        if artifact.local_path is None:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Repository artifact has no local path",
            )
            
        request = SandboxExecutionRequest(
            repository_path=Path(artifact.local_path),
            argv=[
                "python",
                "-c",
                self.SYNTAX_SCRIPT,
            ],
            policy=self.policy,
        )
        
        result = await self.runner.execute(request)
        
        details: dict[str, object] = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "timed_out": result.timed_out,
            "output_truncated": result.output_truncated,
        }
        
        if result.timed_out:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Python syntax check timed out",
                details=details,
                command="python -c <syntax-check>",
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
            
        if result.exit_code != 0:
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.FAILED,
                summary="Python syntax check failed",
                details=details,
                command="python -c <syntax-check>",
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
        
        if "checked=0" in result.stdout.splitlines():
            return ValidationCheck(
                kind=self.kind,
                status=ValidationCheckStatus.SKIPPED,
                summary="Repository has no Python source files",
                details=details,
                command="python -c <syntax-check>",
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
            )
            
        return ValidationCheck(
            kind=self.kind,
            status=ValidationCheckStatus.PASSED,
            summary="Python source syntax is valid",
            details=details,
            command="python -c <syntax-check>",
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
        )
