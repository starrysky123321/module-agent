import asyncio
from datetime import date
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from module_agent.cli.run_release_acceptance import (
    AcceptanceConfig,
    AcceptanceStage,
    AcceptanceStageResult,
    ReleaseAcceptanceReport,
    run_release_acceptance,
)
from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.literature.domain.run import (
    LiteratureRun,
    LiteratureRunStatus,
)
from module_agent.literature.domain.search import SearchRequest
from module_agent.code.domain import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    CodePaperInput,
    ReproductionPlan,
)
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationStatus,
)
from module_agent.workflow.domain import WorkflowStatus
from module_agent.workflow.result import ModuleBuildResult
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunStatus,
)


def _search_request(*, max_results: int = 5) -> SearchRequest:
    return SearchRequest(
        topic="graph neural network node classification",
        description="Find one representative implementation paper",
        start_date=date(2023, 1, 1),
        end_date=date(2026, 12, 31),
        keywords=["graph neural network", "node classification"],
        max_results=max_results,
    )


def _completed_result() -> ModuleBuildResult:
    paper = CodePaperInput(
        paper_id=51,
        source="openalex",
        source_id="W51",
        title="Representative GNN Paper",
    )
    artifact = CodeArtifact(
        paper_id=51,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem="Node classification",
            implementation_steps=["Implement message passing"],
        ),
    )
    report = ValidationReport(
        literature_run_id=7,
        paper_id=51,
        artifact_origin=artifact.origin,
        artifact_status=artifact.status,
        mode=ValidationMode.STATIC,
        status=ValidationStatus.PASSED,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.REPRODUCTION_PLAN,
                status=ValidationCheckStatus.PASSED,
                summary="Reproduction plan is complete",
            )
        ],
    )
    return ModuleBuildResult(
        literature_run_id=7,
        status=WorkflowStatus.COMPLETED,
        selected_paper_ids=[51],
        selected_papers=[paper],
        code_artifacts=[artifact],
        validation_reports=[report],
    )


def test_acceptance_config_accepts_safe_defaults() -> None:
    config = AcceptanceConfig(search_request=_search_request())

    assert str(config.base_url) == "http://127.0.0.1:8000/"
    assert config.paper_count == 1
    assert config.poll_interval_seconds == 2.0
    assert config.timeout_seconds == 1800


def test_acceptance_config_rejects_selection_over_search_limit() -> None:
    with pytest.raises(ValidationError, match="paper_count cannot exceed"):
        AcceptanceConfig(
            search_request=_search_request(max_results=1),
            paper_count=2,
        )


def test_passed_report_requires_final_result() -> None:
    with pytest.raises(ValidationError, match="requires a final result"):
        ReleaseAcceptanceReport(passed=True, literature_run_id=7)


def test_failed_report_requires_error() -> None:
    with pytest.raises(ValidationError, match="requires an error"):
        ReleaseAcceptanceReport(passed=False, literature_run_id=7)


def test_successful_report_keeps_stage_evidence() -> None:
    stage = AcceptanceStageResult(
        stage=AcceptanceStage.CREATE_RUN,
        passed=True,
        duration_ms=25,
    )

    report = ReleaseAcceptanceReport(
        passed=True,
        literature_run_id=7,
        stages=[stage],
        result=_completed_result(),
    )

    assert report.stages == [stage]
    assert report.result is not None
    assert report.result.status is WorkflowStatus.COMPLETED


def test_successful_report_rejects_mismatched_run_id() -> None:
    with pytest.raises(ValidationError, match="literature_run_id must match"):
        ReleaseAcceptanceReport(
            passed=True,
            literature_run_id=8,
            result=_completed_result(),
        )


def _literature_run_payload(
    status: LiteratureRunStatus,
    *,
    error: str | None = None,
) -> dict[str, object]:
    return LiteratureRun(
        id=7,
        status=status,
        request=_search_request(),
        error=error,
    ).model_dump(mode="json")


def _workflow_run_payload(
    status: ModuleWorkflowRunStatus,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    terminal = status in {
        ModuleWorkflowRunStatus.COMPLETED,
        ModuleWorkflowRunStatus.FAILED,
        ModuleWorkflowRunStatus.CANCELLED,
        ModuleWorkflowRunStatus.TIMED_OUT,
    }
    return ModuleWorkflowRun(
        literature_run_id=7,
        trace_id=uuid4(),
        status=status,
        deadline_at=now + timedelta(minutes=10),
        finished_at=now if terminal else None,
        error="workflow failed" if status is ModuleWorkflowRunStatus.FAILED else None,
    ).model_dump(mode="json")


def _paper_payload() -> dict[str, object]:
    return LiteraturePaperRecommendation(
        id=51,
        source="openalex",
        source_id="W51",
        title="Representative GNN Paper",
        authors=["Alice"],
        position=0,
        relevance_score=0.95,
        relevance_reason="Direct match",
    ).model_dump(mode="json")


def test_runner_completes_the_public_api_workflow() -> None:
    seen_authorization: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        seen_authorization.append(request.headers.get("Authorization", ""))
        route = (request.method, request.url.path)
        responses: dict[tuple[str, str], object] = {
            ("POST", "/api/literature/runs"): _literature_run_payload(
                LiteratureRunStatus.PENDING
            ),
            ("POST", "/api/literature/runs/7/workflow/start"): {
                "literature_run_id": 7,
                "message": "Waiting for literature search to complete",
            },
            ("GET", "/api/literature/runs/7"): _literature_run_payload(
                LiteratureRunStatus.COMPLETED
            ),
            (
                "POST",
                "/api/literature/runs/7/workflow/literature/resume",
            ): {
                "literature_run_id": 7,
                "message": "Please select papers before continuing",
            },
            ("GET", "/api/literature/runs/7/papers"): [_paper_payload()],
            ("POST", "/api/literature/runs/7/selection"): {
                "run_id": 7,
                "selected_paper_ids": [51],
            },
            ("GET", "/api/workflow/runs/7"): _workflow_run_payload(
                ModuleWorkflowRunStatus.COMPLETED
            ),
            ("GET", "/api/workflow/runs/7/result"): (
                _completed_result().model_dump(mode="json")
            ),
        }
        return httpx.Response(200, json=responses[route])

    config = AcceptanceConfig(
        base_url="http://test",
        search_request=_search_request(),
        poll_interval_seconds=0.001,
    )
    report = asyncio.run(
        run_release_acceptance(
            config,
            token="acceptance-token",
            transport=httpx.MockTransport(handle),
        )
    )

    assert report.passed is True
    assert report.literature_run_id == 7
    assert report.selected_paper_ids == [51]
    assert [stage.stage for stage in report.stages] == list(AcceptanceStage)
    assert all(stage.passed for stage in report.stages)
    assert set(seen_authorization) == {"Bearer acceptance-token"}


def test_runner_returns_stage_failure_for_failed_literature_run() -> None:
    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/literature/runs" and request.method == "POST":
            payload = _literature_run_payload(LiteratureRunStatus.PENDING)
        elif request.url.path.endswith("/workflow/start"):
            payload = {"literature_run_id": 7}
        else:
            payload = _literature_run_payload(
                LiteratureRunStatus.FAILED,
                error="source unavailable",
            )
        return httpx.Response(200, json=payload)

    report = asyncio.run(
        run_release_acceptance(
            AcceptanceConfig(
                base_url="http://test",
                search_request=_search_request(),
                poll_interval_seconds=0.001,
            ),
            transport=httpx.MockTransport(handle),
        )
    )

    assert report.passed is False
    assert report.error == "source unavailable"
    assert report.stages[-1].stage is AcceptanceStage.WAIT_LITERATURE
    assert report.stages[-1].passed is False
