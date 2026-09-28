from pathlib import Path

from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.ports import (
    CodeWorkspace,
    RepositoryAnalyzer,
    RepositoryFetcher,
    RepositorySearcher,
    ReproductionBuilder,
    ReproductionPlanner,
    ReproductionCodeGenerator,
)

from module_agent.code.domain.artifact import (
    CodeAvailabilityStatus,
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
)
from module_agent.code.domain.request import CodeAgentRequest, CodePaperInput
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryOrigin,
)
import asyncio


class CodeAgent:
    """为选中论文获取可信仓库，或回退为复现计划。"""

    def __init__(
        self,
        *,
        searcher: RepositorySearcher,
        fetcher: RepositoryFetcher,
        planner: ReproductionPlanner,
        workspace: CodeWorkspace,
        analyzer: RepositoryAnalyzer | None = None,
        reproduction_builder: ReproductionBuilder | None = None,
        reproduction_code_generator: ReproductionCodeGenerator | None = None,
        scorer: RepositoryScoringService | None = None,
        confidence_threshold: float = 0.7,
        search_limit: int = 10,
    ) -> None:
        """注入仓库搜索、获取、规划和工作区能力。"""
        if confidence_threshold < 0 or confidence_threshold > 1:
            raise ValueError("confidence_threshold 必须在 0 到 1 之间")
        if search_limit <= 0:
            raise ValueError("search_limit 必须大于 0")
        if scorer is None:
            scorer = RepositoryScoringService()
        
        self.searcher = searcher  # 发现仓库候选。
        self.fetcher = fetcher  # 安全浅克隆可信仓库。
        self.planner = planner  # 无可信仓库时生成复现计划。
        self.workspace = workspace  # 分配隔离的本地目录。
        self.analyzer = analyzer  # 静态识别仓库依赖和入口。
        self.reproduction_builder = reproduction_builder  # 生成复现骨架。
        self.reproduction_code_generator = reproduction_code_generator
        self.scorer = scorer  # 根据证据计算候选可信度。
        self.confidence_threshold = confidence_threshold  # 最低可信门槛。
        self.search_limit = search_limit  # 每篇论文最多搜索数量。
    
    
    async def run(self, request: CodeAgentRequest) -> list[CodeArtifact]:
        """并发处理请求中的所有已选论文。"""
        artifacts = await asyncio.gather(
            *(
                self._process_paper_safely(request, paper)
                for paper in request.papers
            )
        )
        
        return list(artifacts)


    async def _build_reproduction_artifact(
        self,
        paper: CodePaperInput,
        code_requirements: str | None = None,
        *,
        literature_run_id: int | None = None,
    ) -> CodeArtifact:
        """生成没有可信仓库时的结构化复现产物。"""
        plan = await self.planner.plan(paper, code_requirements=code_requirements)

        local_path: str | None = None
        file_manifest: list[str] = []
        warnings = list(plan.warnings)
        implementation = None
        if self.reproduction_code_generator is not None:
            try:
                implementation = (
                    await self.reproduction_code_generator.generate(
                        paper,
                        plan,
                        code_requirements=code_requirements,
                    )
                )
                warnings.extend(implementation.warnings)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                warnings.append(
                    f"Candidate implementation generation failed: {message}"
                )
        if self.reproduction_builder is not None and literature_run_id is not None:
            try:
                scaffold = await self.reproduction_builder.build(
                    self.workspace.reproduction_path(
                        literature_run_id,
                        paper.paper_id,
                    ),
                    paper,
                    plan,
                    implementation=implementation,
                )
                local_path = scaffold.local_path
                file_manifest = scaffold.files
                warnings.append(
                    "Generated files are an unverified reproduction scaffold, "
                    "not a completed implementation of the paper"
                )
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                warnings.append(
                    f"Reproduction scaffold generation failed: {message}"
                )
        
        return CodeArtifact(
            paper_id=paper.paper_id,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
            reproduction_plan=plan,
            implementation_generated=implementation is not None,
            local_path=local_path,
            file_manifest=file_manifest,
            code_availability=CodeAvailabilityStatus.NOT_FOUND,
            warnings=list(dict.fromkeys(warnings)),
        )
        
    async def _build_repository_artifact(
        self,
        *,
        literature_run_id: int,
        paper: CodePaperInput,
        candidate: RepositoryCandidate,
        code_requirements: str | None = None,
    ) -> CodeArtifact:
        """拉取可信仓库并转换为可追踪的代码产物。"""
        destination = self.workspace.repository_path(literature_run_id, paper.paper_id)
        checkout = await self.fetcher.fetch(candidate, destination)

        analysis = None
        warnings: list[str] = []
        if self.analyzer is not None:
            try:
                analysis = await self.analyzer.analyze(
                    Path(checkout.local_path),
                    paper,
                    code_requirements=code_requirements,
                )
                warnings.extend(analysis.warnings)
            except Exception as exc:
                message = str(exc).strip() or type(exc).__name__
                warnings.append(f"Repository analysis failed: {message}")
        
        if candidate.origin is RepositoryOrigin.OFFICIAL:
            artifact_origin = CodeArtifactOrigin.OFFICIAL
        elif candidate.origin is RepositoryOrigin.AUTHOR:
            artifact_origin = CodeArtifactOrigin.AUTHOR
        else:
            artifact_origin = CodeArtifactOrigin.THIRD_PARTY


        return CodeArtifact(
            paper_id=paper.paper_id,
            origin=artifact_origin,
            status=CodeArtifactStatus.REPOSITORY_READY,
            repository_url=checkout.repository_url,
            commit_sha=checkout.commit_sha,
            default_branch=candidate.default_branch,
            license_spdx=candidate.license_spdx,
            local_path=checkout.local_path,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            code_availability=(
                CodeAvailabilityStatus.OPEN_SOURCE
                if candidate.license_spdx
                else CodeAvailabilityStatus.SOURCE_AVAILABLE
            ),
            repository_analysis=analysis,
            warnings=warnings,
        )
        
    
    async def _process_paper(
        self,
        request: CodeAgentRequest,
        paper: CodePaperInput,
    ) -> CodeArtifact:
        """搜索并评分候选，决定获取仓库还是生成复现计划。"""
        candidates = await self.searcher.search(paper, limit=self.search_limit)
        
        scored_candidates = self.scorer.score_many(
            paper,
            candidates,
        )
        
        if (
            not scored_candidates
            or scored_candidates[0].confidence < self.confidence_threshold
        ):
            return await self._build_reproduction_artifact(
                paper,
                request.code_requirements,
                literature_run_id=request.literature_run_id,
            )
        
        return await self._build_repository_artifact(
            literature_run_id=request.literature_run_id,
            paper=paper,
            candidate=scored_candidates[0],
            code_requirements=request.code_requirements,
        )


    async def _process_paper_safely(
        self,
        request: CodeAgentRequest,
        paper: CodePaperInput,
    ) -> CodeArtifact:
        """隔离单篇论文异常，避免影响同批其他论文。"""
        try:
            return await self._process_paper(request, paper)
        except Exception as exc:
            error_message = str(exc).strip() or type(exc).__name__

        return CodeArtifact(
            paper_id=paper.paper_id,
            origin=CodeArtifactOrigin.UNKNOWN,
            status=CodeArtifactStatus.FAILED,
            error=error_message,
        )
