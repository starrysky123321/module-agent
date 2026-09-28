from collections.abc import Sequence
from pathlib import Path




class LocalRepositoryFileInspector:
    """封装 LocalRepositoryFileInspector 相关的数据和行为。"""
    def __init__(self, allowed_root: Path) -> None:
        """初始化当前对象。"""
        self.allowed_root = allowed_root.resolve()


    def list_root_files(self, repository: Path) -> Sequence[str]:
        """列出仓库根目录文件。"""
        resolved_repository = repository.resolve()
        if (
            not resolved_repository.is_relative_to(self.allowed_root) or
            not resolved_repository.is_dir()
        ):
            return ()
        
        repository_files = (
            entry.name
            for entry in resolved_repository.iterdir()
            if entry.is_file()
        )
        
        return tuple(sorted(repository_files, key=str.casefold))
        
