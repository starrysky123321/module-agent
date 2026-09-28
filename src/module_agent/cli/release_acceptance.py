"""Reusable models and runner for release acceptance workflows."""

import asyncio
from collections.abc import Awaitable, Callable
from enum import StrEnum
from time import perf_counter
from typing import Annotated, Self, TypeVar

import httpx
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator

from module_agent.literature.domain.recommendation import (
    LiteraturePaperRecommendation,
)
from module_agent.literature.domain.run import (
    LiteratureRun,
    LiteratureRunStatus,
)
from module_agent.literature.domain.search import SearchRequest
from module_agent.workflow.domain import WorkflowStatus
from module_agent.workflow.lifecycle import (
    ModuleWorkflowRun,
    ModuleWorkflowRunStatus,
)
from module_agent.workflow.result import ModuleBuildResult


T = TypeVar("T")


class AcceptanceStage(StrEnum):
    """Stable names for the steps in one release acceptance run."""

    CREATE_RUN = "create_run"
    START_WORKFLOW = "start_workflow"
    WAIT_LITERATURE = "wait_literature"
    RESUME_LITERATURE = "resume_literature"
    SELECT_PAPERS = "select_papers"
    WAIT_WORKFLOW = "wait_workflow"
    READ_RESULT = "read_result"


class AcceptanceConfig(BaseModel):
    """User-controlled bounds for a safe release acceptance run."""

    # Module Agent API address.
    base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:8000")
    # Literature request used to create the real run.
    search_request: SearchRequest
    # Number of top-ranked papers selected automatically.
    paper_count: Annotated[int, Field(ge=1, le=20)] = 1
    # Optional requirements forwarded to Code Agent.
    code_requirements: Annotated[str, Field(max_length=5000)] | None = None
    # Delay between status requests.
    poll_interval_seconds: Annotated[float, Field(gt=0, le=60)] = 2.0
    # Maximum wall-clock time for the complete acceptance run.
    timeout_seconds: Annotated[int, Field(ge=10, le=86_400)] = 1800

    @model_validator(mode="after")
    def validate_paper_count(self) -> Self:
        """Keep automatic selection within the requested search result limit."""
        if self.paper_count > self.search_request.max_results:
            raise ValueError(
                "paper_count cannot exceed search_request.max_results"
            )
        return self


class AcceptanceStageResult(BaseModel):
    """Outcome and elapsed time of one acceptance stage."""

    stage: AcceptanceStage
    passed: bool
    duration_ms: Annotated[int, Field(ge=0)]
    message: Annotated[str, Field(min_length=1, max_length=2000)] | None = None


class ReleaseAcceptanceReport(BaseModel):
    """Machine-readable final report for a release acceptance run."""

    passed: bool
    literature_run_id: Annotated[int, Field(gt=0)] | None = None
    selected_paper_ids: Annotated[
        list[Annotated[int, Field(gt=0)]],
        Field(max_length=20),
    ] = Field(default_factory=list)
    stages: list[AcceptanceStageResult] = Field(default_factory=list)
    result: ModuleBuildResult | None = None
    error: Annotated[str, Field(min_length=1, max_length=4000)] | None = None

    @model_validator(mode="after")
    def validate_outcome(self) -> Self:
        """Ensure success and failure reports carry consistent evidence."""
        if len(self.selected_paper_ids) != len(set(self.selected_paper_ids)):
            raise ValueError("selected_paper_ids must be unique")

        if self.passed:
            if self.result is None:
                raise ValueError("passed report requires a final result")
            if self.result.status is not WorkflowStatus.COMPLETED:
                raise ValueError("passed report requires a completed result")
            if self.error is not None:
                raise ValueError("passed report cannot contain an error")
            if (
                self.literature_run_id is not None
                and self.result.literature_run_id != self.literature_run_id
            ):
                raise ValueError(
                    "report and result literature_run_id must match"
                )
        elif self.error is None:
            raise ValueError("failed report requires an error")

        return self


class ReleaseAcceptanceRunner:
    """Drive the public API through one complete, static-only workflow."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        config: AcceptanceConfig,
    ) -> None:
        self.client = client
        self.config = config
        self.stages: list[AcceptanceStageResult] = []
        self.literature_run_id: int | None = None
        self.selected_paper_ids: list[int] = []

    async def run(self) -> ReleaseAcceptanceReport:
        """Execute all stages and convert failures into a stable report."""
        try:
            async with asyncio.timeout(self.config.timeout_seconds):
                literature_run = await self._stage(
                    AcceptanceStage.CREATE_RUN,
                    self._create_run,
                )
                run_id = literature_run.id
                assert run_id is not None
                self.literature_run_id = run_id

                await self._stage(
                    AcceptanceStage.START_WORKFLOW,
                    lambda: self._start_workflow(run_id),
                )
                await self._stage(
                    AcceptanceStage.WAIT_LITERATURE,
                    lambda: self._wait_for_literature(run_id),
                )
                await self._stage(
                    AcceptanceStage.RESUME_LITERATURE,
                    lambda: self._resume_after_literature(run_id),
                )
                self.selected_paper_ids = await self._stage(
                    AcceptanceStage.SELECT_PAPERS,
                    lambda: self._select_papers(run_id),
                )
                await self._stage(
                    AcceptanceStage.WAIT_WORKFLOW,
                    lambda: self._wait_for_workflow(run_id),
                )
                result = await self._stage(
                    AcceptanceStage.READ_RESULT,
                    lambda: self._read_result(run_id),
                )
        except Exception as exc:
            message = (str(exc).strip() or type(exc).__name__)[:4000]
            return ReleaseAcceptanceReport(
                passed=False,
                literature_run_id=self.literature_run_id,
                selected_paper_ids=self.selected_paper_ids,
                stages=self.stages,
                error=message,
            )

        return ReleaseAcceptanceReport(
            passed=True,
            literature_run_id=self.literature_run_id,
            selected_paper_ids=self.selected_paper_ids,
            stages=self.stages,
            result=result,
        )

    async def _stage(
        self,
        stage: AcceptanceStage,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        started = perf_counter()
        try:
            value = await operation()
        except Exception as exc:
            message = (str(exc).strip() or type(exc).__name__)[:2000]
            self.stages.append(
                AcceptanceStageResult(
                    stage=stage,
                    passed=False,
                    duration_ms=_elapsed_ms(started),
                    message=message,
                )
            )
            raise
        self.stages.append(
            AcceptanceStageResult(
                stage=stage,
                passed=True,
                duration_ms=_elapsed_ms(started),
            )
        )
        return value

    async def _create_run(self) -> LiteratureRun:
        payload = await self._request_json(
            "POST",
            "/api/literature/runs",
            json=self.config.search_request.model_dump(mode="json"),
        )
        run = LiteratureRun.model_validate(payload)
        if run.id is None:
            raise RuntimeError("Literature API returned no run id")
        return run

    async def _start_workflow(self, run_id: int) -> None:
        await self._request_json(
            "POST",
            f"/api/literature/runs/{run_id}/workflow/start",
            json={
                "code_requirements": self.config.code_requirements,
                "workflow_timeout_seconds": self.config.timeout_seconds,
            },
        )

    async def _wait_for_literature(self, run_id: int) -> LiteratureRun:
        terminal_failures = {
            LiteratureRunStatus.FAILED,
            LiteratureRunStatus.CANCELLED,
        }
        while True:
            payload = await self._request_json(
                "GET",
                f"/api/literature/runs/{run_id}",
            )
            run = LiteratureRun.model_validate(payload)
            if run.status is LiteratureRunStatus.COMPLETED:
                return run
            if run.status in terminal_failures:
                raise RuntimeError(
                    run.error or f"Literature run ended as {run.status.value}"
                )
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _resume_after_literature(self, run_id: int) -> None:
        await self._request_json(
            "POST",
            f"/api/literature/runs/{run_id}/workflow/literature/resume",
        )

    async def _select_papers(self, run_id: int) -> list[int]:
        payload = await self._request_json(
            "GET",
            f"/api/literature/runs/{run_id}/papers",
        )
        papers = [
            LiteraturePaperRecommendation.model_validate(item)
            for item in _require_list(payload, "paper recommendations")
        ]
        if len(papers) < self.config.paper_count:
            raise RuntimeError(
                f"Literature run returned {len(papers)} papers; "
                f"{self.config.paper_count} required"
            )
        selected_ids: list[int] = []
        for paper in papers[: self.config.paper_count]:
            if paper.id is None:
                raise RuntimeError("Paper recommendation has no database id")
            selected_ids.append(paper.id)
        await self._request_json(
            "POST",
            f"/api/literature/runs/{run_id}/selection",
            json={
                "selected_paper_ids": selected_ids,
                "code_requirements": self.config.code_requirements,
            },
        )
        return selected_ids

    async def _wait_for_workflow(self, run_id: int) -> ModuleWorkflowRun:
        terminal_failures = {
            ModuleWorkflowRunStatus.FAILED,
            ModuleWorkflowRunStatus.CANCELLED,
            ModuleWorkflowRunStatus.TIMED_OUT,
        }
        while True:
            payload = await self._request_json(
                "GET",
                f"/api/workflow/runs/{run_id}",
            )
            run = ModuleWorkflowRun.model_validate(payload)
            if run.status is ModuleWorkflowRunStatus.COMPLETED:
                return run
            if run.status in terminal_failures:
                raise RuntimeError(
                    run.error or f"Workflow ended as {run.status.value}"
                )
            await asyncio.sleep(self.config.poll_interval_seconds)

    async def _read_result(self, run_id: int) -> ModuleBuildResult:
        payload = await self._request_json(
            "GET",
            f"/api/workflow/runs/{run_id}/result",
        )
        result = ModuleBuildResult.model_validate(payload)
        if result.status is not WorkflowStatus.COMPLETED:
            raise RuntimeError(
                f"Acceptance workflow ended as {result.status.value}"
            )
        return result

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
    ) -> object:
        response = await self.client.request(method, path, json=json)
        if not response.is_success:
            detail = _response_error_detail(response)
            raise RuntimeError(
                f"{method} {path} returned {response.status_code}: {detail}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                f"{method} {path} returned invalid JSON"
            ) from exc


async def run_release_acceptance(
    config: AcceptanceConfig,
    *,
    token: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
) -> ReleaseAcceptanceReport:
    """Create the HTTP client and execute one acceptance workflow."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(
        base_url=str(config.base_url),
        headers=headers,
        timeout=min(float(config.timeout_seconds), 30.0),
        transport=transport,
        follow_redirects=False,
    ) as client:
        return await ReleaseAcceptanceRunner(client, config).run()


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RuntimeError(f"API returned invalid {label}")
    return value


def _response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text[:500] or "empty response"
    if isinstance(payload, dict):
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail[:500]
    return "request failed"


def _elapsed_ms(started: float) -> int:
    return max(round((perf_counter() - started) * 1000), 0)
