from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from module_agent.code.domain.artifact import (
    CodeArtifact,
    RepositoryAnalysis,
    RepositoryCheckout,
    ReproductionPlan,
    ReproductionScaffold,
    GeneratedImplementation,
)
from module_agent.code.domain.repository import RepositoryCandidate
from module_agent.code.domain.request import CodePaperInput
from module_agent.supervision.domain.advice import (
    SupervisorFailureObservation,
)



class SupervisorObservationSink(Protocol):
    """保存 Supervisor 决策观察记录的端口。"""

    async def record(
        self,
        observation: SupervisorFailureObservation,
    ) -> None:
        """保存一次失败决策观察。"""
        ...


class RepositorySearcher(Protocol):
    """根据论文寻找代码仓库候选的端口。"""

    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> Sequence[RepositoryCandidate]:
        """返回与论文可能相关的仓库候选。"""
        ...


class RepositoryFetcher(Protocol):
    """安全获取已确认仓库的端口。"""

    async def fetch(
        self,
        candidate: RepositoryCandidate,
        destination: Path,
    ) -> RepositoryCheckout:
        """把仓库固定到具体提交并放入目标目录。"""
        ...


class CodeWorkspace(Protocol):
    """为每次论文任务分配隔离工作目录的端口。"""

    def repository_path(
        self,
        literature_run_id: int,
        paper_id: int,
    ) -> Path:
        """返回指定任务和论文的仓库目录。"""
        ...

    def reproduction_path(
        self,
        literature_run_id: int,
        paper_id: int,
    ) -> Path:
        """返回指定论文的复现工程目录。"""
        ...


class ReproductionPlanner(Protocol):
    """没有可信仓库时生成复现计划的端口。"""

    async def plan(
        self,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> ReproductionPlan:
        """根据论文信息和用户要求生成结构化复现计划。"""
        ...


class RepositoryAnalyzer(Protocol):
    """静态分析已获取的仓库。"""

    async def analyze(
        self,
        repository_path: Path,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> RepositoryAnalysis:
        """返回依赖、入口、数据和模块候选摘要。"""
        ...


class ReproductionBuilder(Protocol):
    """把复现计划落成一个明确标记的工程骨架。"""

    async def build(
        self,
        destination: Path,
        paper: CodePaperInput,
        plan: ReproductionPlan,
        *,
        implementation: GeneratedImplementation | None = None,
    ) -> ReproductionScaffold:
        """创建最小工程文件，但不声称完成论文方法。"""
        ...


class ReproductionCodeGenerator(Protocol):
    """Generate a bounded candidate implementation from paper evidence."""

    async def generate(
        self,
        paper: CodePaperInput,
        plan: ReproductionPlan,
        *,
        code_requirements: str | None = None,
    ) -> GeneratedImplementation:
        """Return source and tests without executing either one."""
        ...


class PaperCodeStatusWriter(Protocol):
    """把 Code Agent 结果同步到论文查询模型。"""

    async def write(self, artifacts: Sequence[CodeArtifact]) -> None:
        """幂等更新所处理论文的代码可用性字段。"""
        ...
