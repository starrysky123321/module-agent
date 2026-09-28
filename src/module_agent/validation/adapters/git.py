import asyncio
from pathlib import Path




class LocalGitInspector:
    """封装 LocalGitInspector 相关的数据和行为。"""
    def __init__(
        self,
        allowed_root: Path,
        *,
        git_executable: str = "git",
        timeout_seconds: float = 10.0,
    ) -> None:
        """初始化当前对象。"""
        self.allowed_root = allowed_root.resolve()
        if git_executable.strip() == "":
            raise ValueError("git_executable must be provided")
        self.git_executable = git_executable.strip()
        
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        self.timeout_seconds = timeout_seconds

    async def head_commit(self, path: Path) -> str | None:
        """读取仓库当前提交 SHA。"""
        resolved_path = path.resolve()
        if not resolved_path.is_relative_to(self.allowed_root) or not resolved_path.is_dir():
            return None
        
        process = await asyncio.create_subprocess_exec(
            self.git_executable,
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(resolved_path),
            "rev-parse",
            "--verify",
            "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

                
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=self.timeout_seconds,
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            raise
        
        if process.returncode != 0:
            return None
        
        commit = stdout.decode("utf-8", errors="replace").strip()
        return commit or None
