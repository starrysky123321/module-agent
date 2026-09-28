from pathlib import Path


class LocalWorkspaceInspector:
    """封装 LocalWorkspaceInspector 相关的数据和行为。"""
    def __init__(self, allowed_root: Path) -> None:
        """初始化当前对象。"""
        self.allowed_root = allowed_root.resolve()

    def is_directory(self, path: Path) -> bool:
        """判断路径是否为目录。"""
        resolved_path = path.resolve()
        
        if not resolved_path.is_relative_to(self.allowed_root):
            return False
        
        if resolved_path.is_dir():
            return True
        return False
        
