from pathlib import Path
import asyncio
import shutil
import tempfile

from module_agent.code.domain.artifact import RepositoryCheckout

from module_agent.code.domain.repository import RepositoryCandidate


class GitCommandError(RuntimeError):
    """表示该业务场景的异常。"""
    pass

class GitRepositoryFetcher:
    """封装 GitRepositoryFetcher 相关的数据和行为。"""
    def __init__(self, *, git_executable: str = "git", timeout_seconds: float = 120.0) -> None:
        """初始化当前对象。"""
        if not git_executable.strip():
            raise ValueError("git_executable must be non-empty")
        
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        
        self.git_executable = git_executable.strip()
        self.timeout_seconds = timeout_seconds

    async def _run_git(self, *args: str, cwd: Path | None = None) -> str:
        subprocess = await asyncio.create_subprocess_exec(
            self.git_executable,
            *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        try:
            stdout, stderr = await asyncio.wait_for(
                        subprocess.communicate(),
                        timeout=self.timeout_seconds,
                    )
        except TimeoutError as exc:
            subprocess.kill()
            await subprocess.communicate()
            raise GitCommandError(
                f"Git command timed out after "
                f"{self.timeout_seconds} seconds"
            ) from exc
            
        error_message = stderr.decode("utf-8", errors="replace").strip()
        
        if subprocess.returncode != 0:
            raise GitCommandError(
                error_message or f"Git exited with code {subprocess.returncode}"
            )
        
        return stdout.decode("utf-8", errors="replace").strip()
    
    
    def _validate_fetch_request(self, candidate: RepositoryCandidate, destination: Path) -> Path:
        if candidate.repository_url.scheme != "https":
            raise ValueError("Repository URL must be HTTPS scheme")
        
        if not destination.is_absolute():
            raise ValueError("Destination must be absolute path")
        
        resolved_destination = destination.resolve()
        
        if resolved_destination.exists():
            raise FileExistsError(
                f"Repository destination already exists: "
                f"{resolved_destination}"
            )
        
        return resolved_destination
    
    
    async def fetch(self, candidate: RepositoryCandidate, destination: Path) -> RepositoryCheckout:
        """获取外部资源。"""
        destination = self._validate_fetch_request(candidate, destination)
        
        destination.parent.mkdir(parents=True, exist_ok=True)
        
        temporary_directory = Path(tempfile.mkdtemp(prefix=".clone-", dir=destination.parent))
        
        temporary_repository = temporary_directory / "repository"
        
        try:
            await self._run_git(
                "-c",
                "protocol.file.allow=never",
                "-c",
                "core.hooksPath=/dev/null",
                "clone",
                "--depth",
                "1",
                "--filter=blob:none",
                "--no-tags",
                "--single-branch",
                str(candidate.repository_url),
                str(temporary_repository),
            )
            
            commit_sha = await self._run_git(
                    "-C",
                    str(temporary_repository),
                    "rev-parse",
                    "HEAD",
                )
                
            if destination.exists():
                raise FileExistsError(
                    f"Repository destination already exists: "
                    f"{destination}"
                )
            
            temporary_repository.rename(destination)
            
            return RepositoryCheckout(
                repository_url=candidate.repository_url,
                commit_sha=commit_sha,
                local_path=str(destination),
            )
        
        finally:
            shutil.rmtree(temporary_directory, ignore_errors=True)
        
        
        
        
