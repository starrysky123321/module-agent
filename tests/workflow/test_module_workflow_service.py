import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from module_agent.shared.exceptions import (
    WorkflowAlreadyProgressedError,
    WorkflowNotWaitingForLiteratureError,
    WorkflowNotWaitingForSelectionError,
    WorkflowResultNotReadyError,
)
from module_agent.supervision.domain import (
    WorkflowFailure,
    WorkflowFailureCategory,
)
from module_agent.workflow.domain import (
    PaperSelectionRequest,
    SupervisorStep,
    WorkflowStatus,
)
from module_agent.code.application.agent import CodeAgent
from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)
from module_agent.validation.domain import ValidationReport, ValidationStatus


def _service_with_dispatcher() -> tuple[ModuleWorkflowService, AsyncMock]:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.return_value = "message-7"
    code_input_loader = AsyncMock(spec=SelectedPaperCodeInputLoader)

    async def load_inputs(
        literature_run_id: int,
        paper_ids: list[int],
    ) -> list[CodePaperInput]:
        return [
            CodePaperInput(
                paper_id=paper_id,
                source="openalex",
                source_id=f"W{paper_id}",
                title=f"Paper {paper_id}",
            )
            for paper_id in paper_ids
        ]

    code_input_loader.load.side_effect = load_inputs
    code_agent = AsyncMock(spec=CodeAgent)

    async def build_artifacts(request):
        return [
            CodeArtifact(
                paper_id=paper.paper_id,
                origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
                status=CodeArtifactStatus.REPRODUCTION_PLANNED,
                reproduction_plan=ReproductionPlan(
                    research_problem=paper.title,
                    implementation_steps=["Implement method"],
                ),
            )
            for paper in request.papers
        ]

    code_agent.run.side_effect = build_artifacts
    graph = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=code_agent,
        code_input_loader=code_input_loader,
        validation_agent=build_validation_agent(
            workspace_root=Path.cwd()
        ),
        checkpointer=InMemorySaver(),
    ).build()
    return ModuleWorkflowService(graph), dispatcher


def _service() -> ModuleWorkflowService:
    service, _ = _service_with_dispatcher()
    return service


def test_service_starts_literature_workflow_and_dispatches_once() -> None:
    service, dispatcher = _service_with_dispatcher()

    prompt = asyncio.run(
        service.start_literature_workflow(
            run_id=7,
            code_requirements="Use PyTorch",
        )
    )

    assert prompt.literature_run_id == 7
    assert prompt.message == "Waiting for literature search to complete"
    dispatcher.dispatch.assert_awaited_once_with(
        7,
        resume_workflow=True,
        trace_id=ANY,
    )


def test_service_reuses_literature_interrupt_without_redispatching() -> None:
    service, dispatcher = _service_with_dispatcher()

    async def start_twice():
        first = await service.start_literature_workflow(7)
        second = await service.start_literature_workflow(7)
        return first, second

    first, second = asyncio.run(start_twice())

    assert second == first
    dispatcher.dispatch.assert_awaited_once_with(
        7,
        resume_workflow=True,
        trace_id=ANY,
    )


def test_service_resumes_literature_workflow_into_paper_selection() -> None:
    service, dispatcher = _service_with_dispatcher()

    async def start_and_resume():
        await service.start_literature_workflow(7)
        return await service.resume_literature_workflow(7)

    prompt = asyncio.run(start_and_resume())

    assert prompt.literature_run_id == 7
    assert prompt.message == "Please select papers before continuing"
    dispatcher.dispatch.assert_awaited_once_with(
        7,
        resume_workflow=True,
        trace_id=ANY,
    )


def test_service_rejects_literature_resume_before_start() -> None:
    service = _service()

    with pytest.raises(
        WorkflowNotWaitingForLiteratureError,
        match="not waiting for literature completion",
    ):
        asyncio.run(service.resume_literature_workflow(7))


def test_service_reuses_paper_selection_interrupt_on_duplicate_completion() -> None:
    service = _service()

    async def resume_twice():
        await service.start_literature_workflow(7)
        first = await service.resume_literature_workflow(7)
        second = await service.resume_literature_workflow(7)
        return first, second

    first, second = asyncio.run(resume_twice())

    assert second == first


def test_service_starts_paused_selection_workflow() -> None:
    service = _service()

    prompt = asyncio.run(
        service.start_paper_selection(
            run_id=7,
            code_requirements="Use PyTorch",
        )
    )

    assert prompt.literature_run_id == 7
    assert prompt.message == "Please select papers before continuing"


def test_service_resumes_same_workflow_thread() -> None:
    service = _service()

    async def start_and_resume():
        await service.start_paper_selection(
            run_id=7,
            code_requirements="Use PyTorch",
        )
        return await service.resume_paper_selection(
            run_id=7,
            request=PaperSelectionRequest(selected_paper_ids=[51, 42]),
        )

    state = asyncio.run(start_and_resume())

    assert state["literature_run_id"] == 7
    assert state["selected_paper_ids"] == [51, 42]
    assert state["code_requirements"] == "Use PyTorch"
    assert state["status"] == "completed"
    assert state["next_step"] == "finish"
    assert [item["paper_id"] for item in state["code_artifacts"]] == [51, 42]


def test_service_rejects_resume_before_workflow_is_started() -> None:
    service = _service()

    with pytest.raises(
        WorkflowNotWaitingForSelectionError,
        match="not waiting for paper selection",
    ):
        asyncio.run(
            service.resume_paper_selection(
                7,
                PaperSelectionRequest(selected_paper_ids=[51]),
            )
        )


def test_service_rejects_second_resume_after_selection_is_completed() -> None:
    service = _service()

    async def resume_twice() -> None:
        await service.start_paper_selection(7)
        request = PaperSelectionRequest(selected_paper_ids=[51])
        await service.resume_paper_selection(7, request)
        await service.resume_paper_selection(7, request)

    with pytest.raises(
        WorkflowNotWaitingForSelectionError,
        match="not waiting for paper selection",
    ):
        asyncio.run(resume_twice())


def test_service_returns_existing_interrupt_when_started_twice() -> None:
    service = _service()

    async def start_twice():
        first = await service.start_paper_selection(7)
        second = await service.start_paper_selection(7)
        return first, second

    first, second = asyncio.run(start_twice())

    assert second == first


def test_service_rejects_restart_after_workflow_has_progressed() -> None:
    service = _service()

    async def complete_selection_then_restart() -> None:
        await service.start_paper_selection(7)
        await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51]),
        )
        await service.start_paper_selection(7)

    with pytest.raises(WorkflowAlreadyProgressedError, match="already progressed"):
        asyncio.run(complete_selection_then_restart())


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_service_rejects_invalid_run_id(run_id: int) -> None:
    service = _service()

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(service.start_paper_selection(run_id))

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(
            service.resume_paper_selection(
                run_id,
                PaperSelectionRequest(selected_paper_ids=[1]),
            )
        )


def test_service_rejects_graph_that_does_not_interrupt() -> None:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(interrupts=(), values={})
    )
    graph.ainvoke = AsyncMock(return_value={})
    service = ModuleWorkflowService(graph)

    with pytest.raises(RuntimeError, match="did not pause"):
        asyncio.run(service.start_paper_selection(7))


def test_service_reads_reproduction_artifacts_from_checkpoint() -> None:
    service = _service()

    async def complete_code_step() -> list[CodeArtifact]:
        await service.start_paper_selection(7)
        await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51, 42]),
        )
        return await service.get_code_artifacts(7)

    artifacts = asyncio.run(complete_code_step())

    assert [artifact.paper_id for artifact in artifacts] == [51, 42]
    assert all(
        artifact.status is CodeArtifactStatus.REPRODUCTION_PLANNED
        for artifact in artifacts
    )
    assert artifacts[0].reproduction_plan is not None


def test_service_validates_repository_artifact_from_checkpoint() -> None:
    expected = CodeArtifact(
        paper_id=8,
        origin=CodeArtifactOrigin.AUTHOR,
        status=CodeArtifactStatus.REPOSITORY_READY,
        repository_url="https://github.com/alice/example",
        commit_sha="a" * 40,
        local_path="/workspaces/run-7/paper-8/repository",
        confidence=0.9,
    )
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(
            values={
                "code_artifacts": [expected.model_dump(mode="json")]
            }
        )
    )
    service = ModuleWorkflowService(graph)

    artifacts = asyncio.run(service.get_code_artifacts(7))

    assert artifacts == [expected]
    config = graph.aget_state.await_args.args[0]
    assert config["configurable"]["thread_id"] == "literature-run:7"


def test_service_returns_empty_artifacts_before_code_step() -> None:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={})
    )
    service = ModuleWorkflowService(graph)

    assert asyncio.run(service.get_code_artifacts(7)) == []


def test_service_reads_validation_reports_after_workflow_completion() -> None:
    service = _service()

    async def complete_workflow() -> list[ValidationReport]:
        await service.start_paper_selection(7)
        await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51, 42]),
        )
        return await service.get_validation_reports(7)

    reports = asyncio.run(complete_workflow())

    assert [report.paper_id for report in reports] == [51, 42]
    assert all(report.status is ValidationStatus.PARTIAL for report in reports)


def test_service_returns_empty_reports_before_validation_step() -> None:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(values={})
    )
    service = ModuleWorkflowService(graph)

    assert asyncio.run(service.get_validation_reports(7)) == []


@pytest.mark.parametrize("run_id", [0, -1, True])
def test_service_rejects_invalid_run_id_for_artifact_query(
    run_id: int,
) -> None:
    service = _service()

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(service.get_code_artifacts(run_id))

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(service.get_validation_reports(run_id))

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(service.get_result(run_id))


def test_service_builds_completed_result_from_checkpoint() -> None:
    service = _service()

    async def complete_and_read_result():
        await service.start_paper_selection(7)
        await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51, 42]),
        )
        return await service.get_result(7)

    result = asyncio.run(complete_and_read_result())

    assert result.literature_run_id == 7
    assert result.status is WorkflowStatus.COMPLETED
    assert result.selected_paper_ids == [51, 42]
    assert [paper.paper_id for paper in result.selected_papers] == [51, 42]
    assert [artifact.paper_id for artifact in result.code_artifacts] == [51, 42]
    assert [report.paper_id for report in result.validation_reports] == [51, 42]
    assert result.failure is None


def test_service_builds_final_failed_result_from_checkpoint() -> None:
    failure = WorkflowFailure(
        step=SupervisorStep.VALIDATION,
        category=WorkflowFailureCategory.TIMEOUT,
        message="Validation timed out",
        retryable=False,
        attempt=2,
        error_type="TimeoutError",
    )
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(
            values={
                "literature_run_id": 7,
                "status": WorkflowStatus.FAILED.value,
                "attempts": {SupervisorStep.VALIDATION.value: 2},
                "failure": failure.model_dump(mode="json"),
            }
        )
    )

    result = asyncio.run(ModuleWorkflowService(graph).get_result(7))

    assert result.status is WorkflowStatus.FAILED
    assert result.failure == failure
    assert result.attempts[SupervisorStep.VALIDATION] == 2
    config = graph.aget_state.await_args.args[0]
    assert config["configurable"]["thread_id"] == "literature-run:7"


def test_service_rejects_result_query_while_workflow_is_running() -> None:
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=SimpleNamespace(
            values={
                "literature_run_id": 7,
                "status": WorkflowStatus.VALIDATING.value,
            }
        )
    )

    with pytest.raises(WorkflowResultNotReadyError) as exc_info:
        asyncio.run(ModuleWorkflowService(graph).get_result(7))

    assert exc_info.value.run_id == 7
    assert exc_info.value.status == WorkflowStatus.VALIDATING.value
    assert exc_info.value.status_code == 409


def test_service_deduplicates_result_warnings_in_original_order() -> None:
    service = _service()

    async def complete_and_read_result():
        await service.start_paper_selection(7)
        state = await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51, 42]),
        )
        reports = list(state["validation_reports"])
        reports[0] = {
            **reports[0],
            "warnings": ["shared warning", "first warning"],
        }
        reports[1] = {
            **reports[1],
            "warnings": ["shared warning", "second warning"],
        }
        values = {**state, "validation_reports": reports}
        graph = MagicMock()
        graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(values=values)
        )
        return await ModuleWorkflowService(graph).get_result(7)

    result = asyncio.run(complete_and_read_result())

    assert result.warnings == [
        "shared warning",
        "first warning",
        "second warning",
    ]
