from pathlib import Path



class LocalCodeWorkspace:
    """封装 LocalCodeWorkspace 相关的数据和行为。"""
    def __init__(self, root: Path) -> None:
        """初始化当前对象。"""
        self.root = root.resolve()
    
    def repository_path(self,
                        literature_run_id: int,
                        paper_id: int) -> Path: 
        
        """返回指定论文的隔离仓库目录。"""
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError(
                "literature_run_id must be a positive integer"
            )

        if type(paper_id) is not int or paper_id <= 0:
            raise ValueError(
                "paper_id must be a positive integer"
            )
        
        destination = (
            self.root
            / f"run-{literature_run_id}"
            / f"paper-{paper_id}"
            / "repository"
        ).resolve()
        
        if not destination.is_relative_to(self.root):
            raise ValueError("Repository path escapes workspace root")
        
        
        return destination

    def reproduction_path(
        self,
        literature_run_id: int,
        paper_id: int,
    ) -> Path:
        """返回指定论文的复现工程目录。"""
        if type(literature_run_id) is not int or literature_run_id <= 0:
            raise ValueError(
                "literature_run_id must be a positive integer"
            )
        if type(paper_id) is not int or paper_id <= 0:
            raise ValueError("paper_id must be a positive integer")

        destination = (
            self.root
            / f"run-{literature_run_id}"
            / f"paper-{paper_id}"
            / "reproduction"
        ).resolve()
        if not destination.is_relative_to(self.root):
            raise ValueError("Reproduction path escapes workspace root")
        return destination
