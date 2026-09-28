import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.literature.domain.search import (
    LiteratureBundle,
    PaperSearchResult,
    SearchRequest,
    SourceSearchMetric,
    SourceSearchOutcome,
)
from module_agent.literature.domain.run import LiteratureRun, LiteratureRunStatus
from module_agent.literature.domain.recommendation import LiteratureRunPaper
from module_agent.literature.domain.paper import Paper
from module_agent.literature.domain.ranking import PaperRelevanceAssessment
from module_agent.literature.domain.method import PaperMethodProfile
from module_agent.literature.domain.llm_metric import LlmCallMetric, LlmCallOutcome
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.application.run import LiteratureRunService


def example_request() -> SearchRequest:
    return SearchRequest(
        topic="graph neural networks",
        description="Find representative papers",
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        keywords=["GNN"],
        max_results=10,
    )


def paper(paper_id: int | None) -> Paper:
    return Paper(
        id=paper_id,
        source="openalex",
        source_id=f"W{paper_id}",
        title="Example Paper",
        authors=[],
    )


def paper_result(source_id: str) -> PaperSearchResult:
    return PaperSearchResult(
        source="openalex",
        source_id=source_id,
        title="Example Paper",
    )


def relevance(
    source_id: str,
    score: float,
    reason: str,
) -> PaperRelevanceAssessment:
    return PaperRelevanceAssessment(
        source="openalex",
        source_id=source_id,
        score=score,
        matched_terms=["graph", "neural"],
        reason=reason,
    )


def test_executor_starts_agent_and_completes_run() -> None:
    request = example_request()
    running = LiteratureRun(
        id=7,
        request=request,
        status=LiteratureRunStatus.RUNNING,
    )
    llm_metric = LlmCallMetric(
        stage="method_extraction",
        model="test-qwen",
        item_count=1,
        duration_ms=30.0,
        timeout_seconds=180.0,
        outcome=LlmCallOutcome.SUCCESS,
    )
    bundle = LiteratureBundle(
        request=request,
        search_queries=["graph neural networks", "graph neural networks GNN"],
        selected_papers=[
            paper_result("W20"),
            paper_result("W10"),
        ],
        relevance_assessments=[
            relevance("W20", 0.9, "Direct match"),
            relevance("W10", 0.7, "Partial match"),
        ],
        persisted_papers=[paper(20), paper(10)],
        warnings=["One source was unavailable"],
        source_metrics=[
            SourceSearchMetric(
                source="search_openalex",
                query="graph neural networks",
                duration_ms=125.0,
                result_count=2,
                outcome=SourceSearchOutcome.SUCCESS,
            )
        ],
        llm_metrics=[llm_metric],
    )
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.return_value = bundle
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.start_run.return_value = running
    executor = LiteratureRunExecutor(agent, run_service)

    result = asyncio.run(executor.execute(7))

    assert result is bundle
    run_service.start_run.assert_awaited_once_with(7)
    agent.run.assert_awaited_once_with(request)
    run_service.complete_run.assert_awaited_once_with(
        run_id=7,
        search_queries=bundle.search_queries,
        papers=[
            LiteratureRunPaper(
                paper_id=20,
                position=0,
                relevance_score=0.9,
                relevance_reason="Direct match",
                matched_terms=["graph", "neural"],
            ),
            LiteratureRunPaper(
                paper_id=10,
                position=1,
                relevance_score=0.7,
                relevance_reason="Partial match",
                matched_terms=["graph", "neural"],
            ),
        ],
        warnings=bundle.warnings,
        source_metrics=bundle.source_metrics,
        llm_metrics=bundle.llm_metrics,
    )


def test_executor_matches_method_profiles_by_paper_identity() -> None:
    request = example_request()
    running = LiteratureRun(
        id=7,
        request=request,
        status=LiteratureRunStatus.RUNNING,
    )
    profile_10 = PaperMethodProfile(
        source="openalex", source_id="W10", module_type="encoder", confidence=0.7
    )
    profile_20 = PaperMethodProfile(
        source="openalex", source_id="W20", module_type="decoder", confidence=0.8
    )
    bundle = LiteratureBundle(
        request=request,
        selected_papers=[paper_result("W20"), paper_result("W10")],
        relevance_assessments=[
            relevance("W20", 0.9, "Direct match"),
            relevance("W10", 0.7, "Partial match"),
        ],
        persisted_papers=[paper(20), paper(10)],
        method_profiles=[profile_10, profile_20],
    )
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.return_value = bundle
    run_service = AsyncMock(spec=LiteratureRunService)
    executor = LiteratureRunExecutor(agent, run_service)

    asyncio.run(executor.execute_started(running))

    run_papers = run_service.complete_run.await_args.kwargs["papers"]
    assert [item.method_profile for item in run_papers] == [
        profile_20,
        profile_10,
    ]
    run_service.fail_run.assert_not_awaited()


def test_executor_rejects_persisted_paper_without_id() -> None:
    request = example_request()
    running = LiteratureRun(
        id=7,
        request=request,
        status=LiteratureRunStatus.RUNNING,
    )
    bundle = LiteratureBundle(
        request=request,
        selected_papers=[paper_result("WNone")],
        relevance_assessments=[relevance("WNone", 0.5, "Match")],
        persisted_papers=[paper(None)],
    )
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.return_value = bundle
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.start_run.return_value = running
    executor = LiteratureRunExecutor(agent, run_service)

    with pytest.raises(RuntimeError, match="missing id"):
        asyncio.run(executor.execute(7))

    run_service.complete_run.assert_not_awaited()
    run_service.fail_run.assert_awaited_once_with(
        7,
        "Persisted paper is missing id",
    )


def test_executor_rejects_selected_paper_without_relevance_assessment() -> None:
    request = example_request()
    running = LiteratureRun(
        id=7,
        request=request,
        status=LiteratureRunStatus.RUNNING,
    )
    bundle = LiteratureBundle(
        request=request,
        selected_papers=[paper_result("W20")],
        persisted_papers=[paper(20)],
    )
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.return_value = bundle
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.start_run.return_value = running
    executor = LiteratureRunExecutor(agent, run_service)

    with pytest.raises(RuntimeError, match="missing relevance assessment"):
        asyncio.run(executor.execute(7))

    run_service.complete_run.assert_not_awaited()
    run_service.fail_run.assert_awaited_once_with(
        7,
        "Selected paper is missing relevance assessment",
    )


def test_executor_marks_agent_failure_and_reraises_original_error() -> None:
    request = example_request()
    running = LiteratureRun(
        id=7,
        request=request,
        status=LiteratureRunStatus.RUNNING,
    )
    original_error = RuntimeError("OpenAlex timed out")
    agent = AsyncMock(spec=LiteratureAgent)
    agent.run.side_effect = original_error
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.start_run.return_value = running
    executor = LiteratureRunExecutor(agent, run_service)

    with pytest.raises(RuntimeError) as captured:
        asyncio.run(executor.execute(7))

    assert captured.value is original_error
    run_service.fail_run.assert_awaited_once_with(7, "OpenAlex timed out")
    run_service.complete_run.assert_not_awaited()


def test_executor_does_not_fail_run_that_cannot_start() -> None:
    start_error = ValueError("Run is not startable")
    agent = AsyncMock(spec=LiteratureAgent)
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.start_run.side_effect = start_error
    executor = LiteratureRunExecutor(agent, run_service)

    with pytest.raises(ValueError) as captured:
        asyncio.run(executor.execute(7))

    assert captured.value is start_error
    agent.run.assert_not_awaited()
    run_service.fail_run.assert_not_awaited()
