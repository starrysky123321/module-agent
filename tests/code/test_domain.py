import asyncio
from pathlib import Path

import pytest
from pydantic import ValidationError

from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
    RepositoryCheckout,
)
from module_agent.code.domain.ports import (
    RepositoryFetcher,
    RepositorySearcher,
    ReproductionPlanner,
)
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodeAgentRequest, CodePaperInput


def make_paper(paper_id: int = 1) -> CodePaperInput:
    return CodePaperInput(
        paper_id=paper_id,
        source="openalex",
        source_id=f"W{paper_id}",
        title="A Reliable Graph Learning Method",
        authors=["Alice Example"],
        doi="10.1000/example",
    )


def make_candidate() -> RepositoryCandidate:
    return RepositoryCandidate(
        full_name="alice/reliable-graph-learning",
        repository_url="https://github.com/alice/reliable-graph-learning",
        owner_login="alice",
        default_branch="main",
        license_spdx="MIT",
        origin=RepositoryOrigin.AUTHOR,
        confidence=0.9,
        evidence=[
            RepositoryEvidence(
                evidence_type=RepositoryEvidenceType.DOI,
                description="README contains the paper DOI",
                weight=0.9,
            )
        ],
    )


def test_code_agent_request_contains_selected_paper_details() -> None:
    request = CodeAgentRequest(
        literature_run_id=7,
        papers=[make_paper()],
        code_requirements="  Use PyTorch  ",
    )

    assert request.literature_run_id == 7
    assert request.papers[0].paper_id == 1
    assert request.code_requirements == "Use PyTorch"
    assert "literature" not in type(request).model_fields


def test_code_agent_request_rejects_duplicate_paper_ids() -> None:
    with pytest.raises(ValidationError, match="unique paper ids"):
        CodeAgentRequest(
            literature_run_id=7,
            papers=[make_paper(), make_paper()],
        )


def test_code_agent_request_normalizes_empty_requirements() -> None:
    request = CodeAgentRequest(
        literature_run_id=7,
        papers=[make_paper()],
        code_requirements="   ",
    )

    assert request.code_requirements is None


@pytest.mark.parametrize("run_id", [0, -1])
def test_code_agent_request_rejects_invalid_run_id(run_id: int) -> None:
    with pytest.raises(ValidationError):
        CodeAgentRequest(
            literature_run_id=run_id,
            papers=[make_paper()],
        )


def test_repository_candidate_preserves_evidence() -> None:
    candidate = make_candidate()

    assert candidate.origin is RepositoryOrigin.AUTHOR
    assert candidate.confidence == 0.9
    assert candidate.evidence[0].evidence_type is RepositoryEvidenceType.DOI


def test_ready_repository_artifact_requires_checkout_metadata() -> None:
    with pytest.raises(ValidationError, match="requires repository_url"):
        CodeArtifact(
            paper_id=1,
            origin=CodeArtifactOrigin.AUTHOR,
            status=CodeArtifactStatus.REPOSITORY_READY,
        )


def test_reproduction_artifact_requires_plan() -> None:
    with pytest.raises(ValidationError, match="requires a reproduction plan"):
        CodeArtifact(
            paper_id=1,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        )


def test_reproduction_artifact_accepts_structured_plan() -> None:
    artifact = CodeArtifact(
        paper_id=1,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Graph oversmoothing",
            implementation_steps=["Implement rank-based measurements"],
            inputs=["node features"],
            outputs=["effective rank"],
        ),
    )

    assert artifact.reproduction_plan is not None
    assert artifact.reproduction_plan.outputs == ["effective rank"]


def test_failed_artifact_requires_error() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        CodeArtifact(
            paper_id=1,
            origin=CodeArtifactOrigin.THIRD_PARTY,
            status=CodeArtifactStatus.FAILED,
        )


def test_repository_ports_accept_domain_contracts(tmp_path: Path) -> None:
    class FakeSearcher:
        async def search(
            self,
            paper: CodePaperInput,
            *,
            limit: int = 10,
        ) -> list[RepositoryCandidate]:
            assert paper.paper_id == 1
            assert limit == 3
            return [make_candidate()]

    class FakeFetcher:
        async def fetch(
            self,
            candidate: RepositoryCandidate,
            destination: Path,
        ) -> RepositoryCheckout:
            return RepositoryCheckout(
                repository_url=candidate.repository_url,
                commit_sha="a" * 40,
                local_path=str(destination),
            )

    class FakePlanner:
        async def plan(
            self,
            paper: CodePaperInput,
            *,
            code_requirements: str | None = None,
        ) -> ReproductionPlan:
            return ReproductionPlan(
                research_problem=paper.title,
                implementation_steps=[code_requirements or "Implement method"],
            )

    searcher: RepositorySearcher = FakeSearcher()
    fetcher: RepositoryFetcher = FakeFetcher()
    planner: ReproductionPlanner = FakePlanner()

    async def exercise_ports() -> tuple[RepositoryCheckout, ReproductionPlan]:
        candidates = await searcher.search(make_paper(), limit=3)
        checkout = await fetcher.fetch(candidates[0], tmp_path)
        plan = await planner.plan(make_paper(), code_requirements="Use PyTorch")
        return checkout, plan

    checkout, plan = asyncio.run(exercise_ports())

    assert checkout.commit_sha == "a" * 40
    assert checkout.local_path == str(tmp_path)
    assert plan.implementation_steps == ["Use PyTorch"]
