import asyncio
from pathlib import Path

import pytest

from module_agent.code.adapters.reproduction import LocalReproductionBuilder
from module_agent.code.adapters.workspace import LocalCodeWorkspace
from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.scoring import RepositoryScoringService
from module_agent.code.domain.artifact import (
    CodeAvailabilityStatus,
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
    RepositoryCheckout,
)
from module_agent.code.domain.repository import (
    RepositoryCandidate,
    RepositoryEvidence,
    RepositoryEvidenceType,
    RepositoryOrigin,
)
from module_agent.code.domain.request import CodeAgentRequest, CodePaperInput


class FakeSearcher:
    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[RepositoryCandidate]:
        return []


class FakeFetcher:
    async def fetch(
        self,
        candidate: RepositoryCandidate,
        destination: Path,
    ) -> RepositoryCheckout:
        raise AssertionError("fetch must not run during construction")


class FakePlanner:
    async def plan(
        self,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> ReproductionPlan:
        raise AssertionError("plan must not run during construction")


class FakeWorkspace:
    def repository_path(
        self,
        literature_run_id: int,
        paper_id: int,
    ) -> Path:
        raise AssertionError("workspace must not run during construction")


class RecordingPlanner:
    def __init__(self, result: ReproductionPlan) -> None:
        self.result = result
        self.calls: list[tuple[CodePaperInput, str | None]] = []

    async def plan(
        self,
        paper: CodePaperInput,
        *,
        code_requirements: str | None = None,
    ) -> ReproductionPlan:
        self.calls.append((paper, code_requirements))
        return self.result


class RecordingWorkspace:
    def __init__(self, result: Path) -> None:
        self.result = result
        self.calls: list[tuple[int, int]] = []

    def repository_path(
        self,
        literature_run_id: int,
        paper_id: int,
    ) -> Path:
        self.calls.append((literature_run_id, paper_id))
        return self.result


class RecordingFetcher:
    def __init__(self, result: RepositoryCheckout) -> None:
        self.result = result
        self.calls: list[tuple[RepositoryCandidate, Path]] = []

    async def fetch(
        self,
        candidate: RepositoryCandidate,
        destination: Path,
    ) -> RepositoryCheckout:
        self.calls.append((candidate, destination))
        return self.result


class RecordingSearcher:
    def __init__(self, result: list[RepositoryCandidate]) -> None:
        self.result = result
        self.calls: list[tuple[CodePaperInput, int]] = []

    async def search(
        self,
        paper: CodePaperInput,
        *,
        limit: int = 10,
    ) -> list[RepositoryCandidate]:
        self.calls.append((paper, limit))
        return self.result


def build_agent(**updates: object) -> CodeAgent:
    values = {
        "searcher": FakeSearcher(),
        "fetcher": FakeFetcher(),
        "planner": FakePlanner(),
        "workspace": FakeWorkspace(),
    }
    values.update(updates)
    return CodeAgent(**values)  # type: ignore[arg-type]


def make_request(paper: CodePaperInput) -> CodeAgentRequest:
    return CodeAgentRequest(
        literature_run_id=12,
        papers=[paper],
        code_requirements="Use PyTorch",
    )


def make_scored_candidate(
    *,
    full_name: str,
    confidence: float,
) -> RepositoryCandidate:
    return RepositoryCandidate(
        full_name=full_name,
        repository_url=f"https://github.com/{full_name}",
        owner_login=full_name.split("/", maxsplit=1)[0],
        evidence=[
            RepositoryEvidence(
                evidence_type=RepositoryEvidenceType.DOI,
                description=f"Evidence for {full_name}",
                weight=confidence,
            )
        ],
    )


def test_agent_constructor_stores_dependencies_without_using_them() -> None:
    searcher = FakeSearcher()
    fetcher = FakeFetcher()
    planner = FakePlanner()
    workspace = FakeWorkspace()
    scorer = RepositoryScoringService()

    agent = CodeAgent(
        searcher=searcher,
        fetcher=fetcher,
        planner=planner,
        workspace=workspace,
        scorer=scorer,
        confidence_threshold=0.8,
        search_limit=4,
    )

    assert agent.searcher is searcher
    assert agent.fetcher is fetcher
    assert agent.planner is planner
    assert agent.workspace is workspace
    assert agent.scorer is scorer
    assert agent.confidence_threshold == 0.8
    assert agent.search_limit == 4


def test_agent_constructor_creates_default_scorer() -> None:
    agent = build_agent()

    assert isinstance(agent.scorer, RepositoryScoringService)


@pytest.mark.parametrize("confidence_threshold", [-0.1, 1.1])
def test_agent_constructor_rejects_invalid_confidence_threshold(
    confidence_threshold: float,
) -> None:
    with pytest.raises(ValueError, match="confidence_threshold"):
        build_agent(confidence_threshold=confidence_threshold)


@pytest.mark.parametrize("confidence_threshold", [0.0, 1.0])
def test_agent_constructor_accepts_threshold_boundaries(
    confidence_threshold: float,
) -> None:
    agent = build_agent(confidence_threshold=confidence_threshold)

    assert agent.confidence_threshold == confidence_threshold


@pytest.mark.parametrize("search_limit", [0, -1])
def test_agent_constructor_rejects_non_positive_search_limit(
    search_limit: int,
) -> None:
    with pytest.raises(ValueError, match="search_limit"):
        build_agent(search_limit=search_limit)


def test_build_reproduction_artifact_wraps_planner_result() -> None:
    paper = CodePaperInput(
        paper_id=5,
        source="openalex",
        source_id="W5",
        title="A Graph Learning Method",
    )
    plan = ReproductionPlan(
        research_problem="Graph representation learning",
        implementation_steps=["Implement the propagation module"],
    )
    planner = RecordingPlanner(plan)
    agent = build_agent(planner=planner)

    artifact = asyncio.run(
        agent._build_reproduction_artifact(paper, "Use PyTorch")
    )

    assert planner.calls == [(paper, "Use PyTorch")]
    assert artifact.paper_id == paper.paper_id
    assert artifact.origin is CodeArtifactOrigin.REPRODUCTION_PLAN
    assert artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED
    assert artifact.reproduction_plan is plan


def test_build_repository_artifact_uses_workspace_and_fetcher(
    tmp_path: Path,
) -> None:
    paper = CodePaperInput(
        paper_id=6,
        source="openalex",
        source_id="W6",
        title="A Reliable Graph Method",
    )
    evidence = RepositoryEvidence(
        evidence_type=RepositoryEvidenceType.DOI,
        description="README contains the paper DOI",
        weight=0.8,
    )
    candidate = RepositoryCandidate(
        full_name="alice/graph-method",
        repository_url="https://github.com/alice/graph-method",
        owner_login="alice",
        default_branch="main",
        license_spdx="MIT",
        origin=RepositoryOrigin.AUTHOR,
        confidence=0.9,
        evidence=[evidence],
    )
    destination = tmp_path / "run-12" / "paper-6" / "repository"
    checkout = RepositoryCheckout(
        repository_url=candidate.repository_url,
        commit_sha="a" * 40,
        local_path=str(destination),
    )
    workspace = RecordingWorkspace(destination)
    fetcher = RecordingFetcher(checkout)
    agent = build_agent(workspace=workspace, fetcher=fetcher)

    artifact = asyncio.run(
        agent._build_repository_artifact(
            literature_run_id=12,
            paper=paper,
            candidate=candidate,
        )
    )

    assert workspace.calls == [(12, 6)]
    assert fetcher.calls == [(candidate, destination)]
    assert artifact.paper_id == 6
    assert artifact.origin is CodeArtifactOrigin.AUTHOR
    assert artifact.status is CodeArtifactStatus.REPOSITORY_READY
    assert artifact.repository_url == checkout.repository_url
    assert artifact.commit_sha == checkout.commit_sha
    assert artifact.local_path == str(destination)
    assert artifact.default_branch == "main"
    assert artifact.license_spdx == "MIT"
    assert artifact.confidence == 0.9
    assert artifact.evidence == [evidence]
    assert artifact.code_availability is CodeAvailabilityStatus.OPEN_SOURCE


@pytest.mark.parametrize(
    ("repository_origin", "artifact_origin"),
    [
        (RepositoryOrigin.OFFICIAL, CodeArtifactOrigin.OFFICIAL),
        (RepositoryOrigin.AUTHOR, CodeArtifactOrigin.AUTHOR),
        (RepositoryOrigin.THIRD_PARTY, CodeArtifactOrigin.THIRD_PARTY),
        (RepositoryOrigin.UNKNOWN, CodeArtifactOrigin.THIRD_PARTY),
    ],
)
def test_build_repository_artifact_maps_repository_origin(
    tmp_path: Path,
    repository_origin: RepositoryOrigin,
    artifact_origin: CodeArtifactOrigin,
) -> None:
    paper = CodePaperInput(
        paper_id=1,
        source="openalex",
        source_id="W1",
        title="Example",
    )
    candidate = RepositoryCandidate(
        full_name="alice/example",
        repository_url="https://github.com/alice/example",
        owner_login="alice",
        origin=repository_origin,
        confidence=0.8,
    )
    checkout = RepositoryCheckout(
        repository_url=candidate.repository_url,
        commit_sha="b" * 40,
        local_path=str(tmp_path / "repository"),
    )
    agent = build_agent(
        workspace=RecordingWorkspace(tmp_path / "repository"),
        fetcher=RecordingFetcher(checkout),
    )

    artifact = asyncio.run(
        agent._build_repository_artifact(
            literature_run_id=1,
            paper=paper,
            candidate=candidate,
        )
    )

    assert artifact.origin is artifact_origin
    assert artifact.code_availability is (
        CodeAvailabilityStatus.SOURCE_AVAILABLE
    )


def test_process_paper_uses_reproduction_plan_when_search_is_empty() -> None:
    paper = CodePaperInput(
        paper_id=3,
        source="openalex",
        source_id="W3",
        title="Example Method",
    )
    searcher = RecordingSearcher([])
    plan = ReproductionPlan(
        research_problem="Example problem",
        implementation_steps=["Implement the method"],
    )
    planner = RecordingPlanner(plan)
    agent = build_agent(
        searcher=searcher,
        planner=planner,
        search_limit=4,
    )

    artifact = asyncio.run(agent._process_paper(make_request(paper), paper))

    assert searcher.calls == [(paper, 4)]
    assert planner.calls == [(paper, "Use PyTorch")]
    assert artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED


def test_process_paper_generates_reproduction_scaffold(
    tmp_path: Path,
) -> None:
    paper = CodePaperInput(
        paper_id=3,
        source="openalex",
        source_id="W3",
        title="Example Method",
    )
    plan = ReproductionPlan(
        research_problem="Example problem",
        implementation_steps=["Implement the method"],
        inputs=["features"],
    )
    agent = build_agent(
        searcher=RecordingSearcher([]),
        planner=RecordingPlanner(plan),
        workspace=LocalCodeWorkspace(tmp_path / "workspaces"),
        reproduction_builder=LocalReproductionBuilder(),
    )

    artifact = asyncio.run(agent._process_paper(make_request(paper), paper))

    assert artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED
    assert artifact.code_availability is CodeAvailabilityStatus.NOT_FOUND
    assert artifact.local_path is not None
    assert "src/paper_reproduction/core.py" in artifact.file_manifest
    assert any("unverified reproduction scaffold" in item for item in artifact.warnings)


def test_process_paper_uses_reproduction_plan_below_threshold() -> None:
    paper = CodePaperInput(
        paper_id=3,
        source="openalex",
        source_id="W3",
        title="Example Method",
    )
    searcher = RecordingSearcher(
        [make_scored_candidate(full_name="alice/low-score", confidence=0.69)]
    )
    plan = ReproductionPlan(
        research_problem="Example problem",
        implementation_steps=["Implement the method"],
    )
    planner = RecordingPlanner(plan)
    agent = build_agent(searcher=searcher, planner=planner)

    artifact = asyncio.run(agent._process_paper(make_request(paper), paper))

    assert planner.calls == [(paper, "Use PyTorch")]
    assert artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED


def test_process_paper_fetches_best_candidate_at_threshold(
    tmp_path: Path,
) -> None:
    paper = CodePaperInput(
        paper_id=3,
        source="openalex",
        source_id="W3",
        title="Example Method",
    )
    lower = make_scored_candidate(
        full_name="alice/lower",
        confidence=0.7,
    )
    best = make_scored_candidate(
        full_name="alice/best",
        confidence=0.9,
    )
    destination = tmp_path / "repository"
    checkout = RepositoryCheckout(
        repository_url=best.repository_url,
        commit_sha="c" * 40,
        local_path=str(destination),
    )
    fetcher = RecordingFetcher(checkout)
    workspace = RecordingWorkspace(destination)
    agent = build_agent(
        searcher=RecordingSearcher([lower, best]),
        fetcher=fetcher,
        workspace=workspace,
        confidence_threshold=0.9,
    )

    artifact = asyncio.run(agent._process_paper(make_request(paper), paper))

    assert workspace.calls == [(12, 3)]
    assert fetcher.calls[0][0].full_name == "alice/best"
    assert artifact.status is CodeArtifactStatus.REPOSITORY_READY
    assert artifact.confidence == 0.9


def test_run_processes_papers_concurrently_and_isolates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    papers = [
        CodePaperInput(
            paper_id=paper_id,
            source="openalex",
            source_id=f"W{paper_id}",
            title=f"Paper {paper_id}",
        )
        for paper_id in (1, 2, 3)
    ]
    request = CodeAgentRequest(
        literature_run_id=8,
        papers=papers,
        code_requirements="Use PyTorch",
    )
    agent = build_agent()
    all_started = asyncio.Event()
    release = asyncio.Event()
    started: list[int] = []

    async def fake_process_paper(
        received_request: CodeAgentRequest,
        paper: CodePaperInput,
    ):
        assert received_request is request
        started.append(paper.paper_id)
        if len(started) == len(papers):
            all_started.set()
        await release.wait()
        if paper.paper_id == 2:
            raise RuntimeError("repository service unavailable")
        return CodeArtifact(
            paper_id=paper.paper_id,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
            reproduction_plan=ReproductionPlan(
                research_problem=paper.title,
                implementation_steps=["Implement method"],
            ),
        )

    monkeypatch.setattr(agent, "_process_paper", fake_process_paper)

    async def exercise_run():
        run_task = asyncio.create_task(agent.run(request))
        await asyncio.wait_for(all_started.wait(), timeout=1)
        release.set()
        return await run_task

    artifacts = asyncio.run(exercise_run())

    assert set(started) == {1, 2, 3}
    assert [artifact.paper_id for artifact in artifacts] == [1, 2, 3]
    assert artifacts[0].status is CodeArtifactStatus.REPRODUCTION_PLANNED
    assert artifacts[1].status is CodeArtifactStatus.FAILED
    assert artifacts[1].origin is CodeArtifactOrigin.UNKNOWN
    assert artifacts[1].error == "repository service unavailable"
    assert artifacts[2].status is CodeArtifactStatus.REPRODUCTION_PLANNED


def test_safe_processing_uses_exception_type_for_empty_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper = CodePaperInput(
        paper_id=1,
        source="openalex",
        source_id="W1",
        title="Paper 1",
    )
    request = make_request(paper)
    agent = build_agent()

    async def fail_without_message(
        received_request: CodeAgentRequest,
        received_paper: CodePaperInput,
    ):
        raise RuntimeError()

    monkeypatch.setattr(agent, "_process_paper", fail_without_message)

    artifact = asyncio.run(agent._process_paper_safely(request, paper))

    assert artifact.status is CodeArtifactStatus.FAILED
    assert artifact.error == "RuntimeError"
