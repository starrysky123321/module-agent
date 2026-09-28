import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from module_agent.shared.exceptions import (
    LiteratureRunNotFoundError,
    LiteratureRunStateError,
    PaperSelectionAlreadyExistsError,
)
from module_agent.literature.domain.run import LiteratureRunStatus
from module_agent.literature.domain.selection import PaperSelection
from module_agent.workflow.domain import (
    LiteratureWaitInterrupt,
    PaperSelectionInterrupt,
    PaperSelectionRequest,
)
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.literature.application.selection import PaperSelectionService
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.code.application.agent import CodeAgent
from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)


@pytest.mark.parametrize(
    "status",
    [
        LiteratureRunStatus.PENDING,
        LiteratureRunStatus.QUEUED,
        LiteratureRunStatus.RUNNING,
    ],
)
def test_coordinator_starts_literature_workflow(
    status: LiteratureRunStatus,
) -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(status=status)
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    prompt = LiteratureWaitInterrupt(literature_run_id=7)
    workflow_service.start_literature_workflow.return_value = prompt
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    result = asyncio.run(
        coordinator.start_literature_workflow(
            7,
            code_requirements="Use PyTorch",
        )
    )

    assert result == prompt
    run_service.get_run.assert_awaited_once_with(7)
    workflow_service.start_literature_workflow.assert_awaited_once_with(
        7,
        "Use PyTorch",
    )


def test_coordinator_rejects_completed_run_when_starting_literature() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.COMPLETED
    )
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    with pytest.raises(LiteratureRunStateError, match="start literature workflow"):
        asyncio.run(coordinator.start_literature_workflow(7))

    workflow_service.start_literature_workflow.assert_not_awaited()


def test_coordinator_resumes_completed_literature_workflow() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.COMPLETED
    )
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    prompt = PaperSelectionInterrupt(literature_run_id=7)
    workflow_service.resume_literature_workflow.return_value = prompt
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    result = asyncio.run(
        coordinator.resume_after_literature_completion(7)
    )

    assert result == prompt
    run_service.get_run.assert_awaited_once_with(7)
    workflow_service.resume_literature_workflow.assert_awaited_once_with(7)


def test_coordinator_rejects_resume_before_literature_is_completed() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.RUNNING
    )
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    with pytest.raises(LiteratureRunStateError, match="resume literature workflow"):
        asyncio.run(coordinator.resume_after_literature_completion(7))

    workflow_service.resume_literature_workflow.assert_not_awaited()


def test_coordinator_starts_selection_for_completed_run() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.COMPLETED
    )
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    prompt = PaperSelectionInterrupt(literature_run_id=7)
    workflow_service.start_paper_selection.return_value = prompt
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    result = asyncio.run(
        coordinator.start_paper_selection(7, code_requirements="Use PyTorch")
    )

    assert result == prompt
    run_service.get_run.assert_awaited_once_with(7)
    workflow_service.start_paper_selection.assert_awaited_once_with(
        7, "Use PyTorch"
    )


def test_coordinator_rejects_unfinished_run_before_starting_workflow() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.RUNNING
    )
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    with pytest.raises(LiteratureRunStateError, match="start paper selection"):
        asyncio.run(coordinator.start_paper_selection(7))

    workflow_service.start_paper_selection.assert_not_awaited()


def test_coordinator_propagates_missing_run_without_starting_workflow() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.side_effect = LiteratureRunNotFoundError(99)
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    with pytest.raises(LiteratureRunNotFoundError, match="Run with id 99"):
        asyncio.run(coordinator.start_paper_selection(99))

    workflow_service.start_paper_selection.assert_not_awaited()


def test_coordinator_confirms_selection_and_resumes_workflow() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    request = PaperSelectionRequest(
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
    )
    saved = PaperSelection(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
    )
    selection_service.confirm_selection.return_value = saved
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    result = asyncio.run(coordinator.confirm_paper_selection(7, request))

    assert result == saved
    selection_service.confirm_selection.assert_awaited_once_with(7, request)
    workflow_service.resume_paper_selection.assert_awaited_once_with(7, request)


def test_coordinator_does_not_resume_when_selection_cannot_be_saved() -> None:
    run_service = AsyncMock(spec=LiteratureRunService)
    workflow_service = AsyncMock(spec=ModuleWorkflowService)
    selection_service = AsyncMock(spec=PaperSelectionService)
    selection_service.confirm_selection.side_effect = (
        PaperSelectionAlreadyExistsError(7)
    )
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )
    request = PaperSelectionRequest(selected_paper_ids=[51])

    with pytest.raises(PaperSelectionAlreadyExistsError):
        asyncio.run(coordinator.confirm_paper_selection(7, request))

    workflow_service.resume_paper_selection.assert_not_awaited()


def test_coordinator_runs_complete_pause_and_resume_cycle() -> None:
    code_input_loader = AsyncMock(spec=SelectedPaperCodeInputLoader)
    code_input_loader.load.return_value = [
        CodePaperInput(
            paper_id=paper_id,
            source="openalex",
            source_id=f"W{paper_id}",
            title=f"Paper {paper_id}",
        )
        for paper_id in (51, 42)
    ]
    code_agent = AsyncMock(spec=CodeAgent)
    code_agent.run.return_value = [
        CodeArtifact(
            paper_id=paper_id,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
            reproduction_plan=ReproductionPlan(
                research_problem=f"Problem {paper_id}",
                implementation_steps=["Implement method"],
            ),
        )
        for paper_id in (51, 42)
    ]
    graph = ModuleBuildWorkflow(
        literature_dispatcher=AsyncMock(spec=LiteratureRunDispatcher),
        code_agent=code_agent,
        code_input_loader=code_input_loader,
        validation_agent=build_validation_agent(
            workspace_root=Path.cwd()
        ),
        checkpointer=InMemorySaver(),
    ).build()
    workflow_service = ModuleWorkflowService(graph)
    run_service = AsyncMock(spec=LiteratureRunService)
    run_service.get_run.return_value = SimpleNamespace(
        status=LiteratureRunStatus.COMPLETED
    )
    selection_service = AsyncMock(spec=PaperSelectionService)
    request = PaperSelectionRequest(
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
    )
    saved = PaperSelection(
        run_id=7,
        selected_paper_ids=[51, 42],
        code_requirements="Use PyTorch",
    )
    selection_service.confirm_selection.return_value = saved
    coordinator = ModuleWorkflowCoordinator(
        workflow_service, run_service, selection_service
    )

    async def run_cycle() -> tuple[PaperSelectionInterrupt, PaperSelection, Any]:
        prompt = await coordinator.start_paper_selection(7)
        selection = await coordinator.confirm_paper_selection(7, request)
        snapshot = await graph.aget_state(
            RunnableConfig(
                configurable={"thread_id": "literature-run:7"}
            )
        )
        return prompt, selection, snapshot

    prompt, selection, snapshot = asyncio.run(run_cycle())

    assert prompt.literature_run_id == 7
    assert selection == saved
    assert snapshot.interrupts == ()
    assert snapshot.values["selected_paper_ids"] == [51, 42]
    assert snapshot.values["code_requirements"] == "Use PyTorch"
    assert snapshot.values["status"] == "completed"
    assert snapshot.values["next_step"] == "finish"
    assert [
        artifact["paper_id"]
        for artifact in snapshot.values["code_artifacts"]
    ] == [51, 42]
