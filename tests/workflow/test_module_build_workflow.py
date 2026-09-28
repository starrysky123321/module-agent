import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from module_agent.workflow.domain import ModuleGraphState
from module_agent.code.application.agent import CodeAgent
from module_agent.code.domain.artifact import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    ReproductionPlan,
)
from module_agent.code.domain.request import CodePaperInput
from module_agent.code.domain.jobs import CodeJobQueue, ComputeTarget
from module_agent.code.application.run import CodeRunService
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.supervision.domain import WorkflowFailure
from module_agent.validation.application.agent import ValidationAgent
from module_agent.validation.domain import (
    ValidationCheck,
    ValidationCheckKind,
    ValidationCheckStatus,
    ValidationMode,
    ValidationReport,
    ValidationStatus,
)
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)


def _validation_agent():
    return build_validation_agent(workspace_root=Path.cwd())


def _dispatcher() -> AsyncMock:
    dispatcher = AsyncMock(spec=LiteratureRunDispatcher)
    dispatcher.dispatch.return_value = "message-7"
    return dispatcher


def _code_agent() -> AsyncMock:
    return AsyncMock(spec=CodeAgent)


def _code_input_loader() -> AsyncMock:
    return AsyncMock(spec=SelectedPaperCodeInputLoader)


def _artifact(paper_id: int = 51) -> CodeArtifact:
    return CodeArtifact(
        paper_id=paper_id,
        origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
        status=CodeArtifactStatus.REPRODUCTION_PLANNED,
        reproduction_plan=ReproductionPlan(
            research_problem=f"Problem {paper_id}",
            implementation_steps=["Implement method"],
        ),
    )


def _report(
    artifact: CodeArtifact,
    *,
    status: ValidationStatus = ValidationStatus.PARTIAL,
) -> ValidationReport:
    check_status = (
        ValidationCheckStatus.FAILED
        if status is ValidationStatus.FAILED
        else ValidationCheckStatus.PASSED
    )
    return ValidationReport(
        literature_run_id=7,
        paper_id=artifact.paper_id,
        artifact_origin=artifact.origin,
        artifact_status=artifact.status,
        mode=ValidationMode.STATIC,
        status=status,
        checks=[
            ValidationCheck(
                kind=ValidationCheckKind.REPRODUCTION_PLAN,
                status=check_status,
                summary="Reproduction plan checked",
            )
        ],
    )


def _paper_selection_graph():
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )
    builder = StateGraph(ModuleGraphState)
    builder.add_node("paper_selection", workflow._paper_selection_node)
    builder.add_edge(START, "paper_selection")
    builder.add_edge("paper_selection", END)
    return builder.compile(checkpointer=workflow.checkpointer)


def _literature_wait_graph():
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )
    builder = StateGraph(ModuleGraphState)
    builder.add_node("literature_wait", workflow._literature_wait_node)
    builder.add_edge(START, "literature_wait")
    builder.add_edge("literature_wait", END)
    return builder.compile(checkpointer=workflow.checkpointer)


def test_module_build_workflow_requires_checkpointer() -> None:
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
    )

    with pytest.raises(ValueError, match="checkpointer must be provided"):
        workflow.build()


def test_paper_selection_node_interrupts_and_resumes() -> None:
    graph = _paper_selection_graph()
    config = {"configurable": {"thread_id": "selection-resume"}}

    paused = graph.invoke(
        {
            "literature_run_id": 7,
            "status": "waiting_for_paper_selection",
            "next_step": "paper_selection",
            "code_requirements": "Keep existing requirement",
        },
        config,
    )

    assert paused["__interrupt__"][0].value == {
        "literature_run_id": 7,
        "message": "Please select papers before continuing",
    }

    resumed = graph.invoke(
        Command(resume={"selected_paper_ids": [51, 42]}),
        config,
    )

    assert resumed["selected_paper_ids"] == [51, 42]
    assert resumed["code_requirements"] == "Keep existing requirement"
    assert resumed["status"] == "preparing_code"
    assert resumed["next_step"] == "code"


def test_paper_selection_resume_can_replace_code_requirements() -> None:
    graph = _paper_selection_graph()
    config = {"configurable": {"thread_id": "selection-requirements"}}
    graph.invoke(
        {
            "literature_run_id": 8,
            "next_step": "paper_selection",
        },
        config,
    )

    resumed = graph.invoke(
        Command(
            resume={
                "selected_paper_ids": [20],
                "code_requirements": "Use JAX",
            }
        ),
        config,
    )

    assert resumed["code_requirements"] == "Use JAX"


def test_literature_wait_node_interrupts_and_resumes() -> None:
    graph = _literature_wait_graph()
    config = {"configurable": {"thread_id": "literature-wait-resume"}}

    paused = graph.invoke(
        {
            "literature_run_id": 7,
            "status": "searching_literature",
            "next_step": "literature",
        },
        config,
    )

    assert paused["__interrupt__"][0].value == {
        "literature_run_id": 7,
        "message": "Waiting for literature search to complete",
    }

    resumed = graph.invoke(
        Command(resume={"literature_run_id": 7}),
        config,
    )

    assert resumed["status"] == "waiting_for_paper_selection"
    assert resumed["next_step"] == "paper_selection"


def test_main_graph_moves_from_literature_wait_to_paper_selection() -> None:
    dispatcher = _dispatcher()
    code_input_loader = _code_input_loader()
    code_input_loader.load.return_value = [
        CodePaperInput(
            paper_id=51,
            source="openalex",
            source_id="W51",
            title="Paper 51",
        ),
        CodePaperInput(
            paper_id=42,
            source="openalex",
            source_id="W42",
            title="Paper 42",
        ),
    ]
    code_agent = _code_agent()
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
        literature_dispatcher=dispatcher,
        code_agent=code_agent,
        code_input_loader=code_input_loader,
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "literature-to-selection"}}

    async def run_flow():
        waiting_for_literature = await graph.ainvoke(
            {
                "literature_run_id": 7,
                "status": "searching_literature",
                "next_step": "literature",
                "code_requirements": "Use PyTorch",
            },
            config,
        )
        waiting_for_selection = await graph.ainvoke(
            Command(resume={"literature_run_id": 7}),
            config,
        )
        completed_selection = await graph.ainvoke(
            Command(resume={"selected_paper_ids": [51, 42]}),
            config,
        )
        return (
            waiting_for_literature,
            waiting_for_selection,
            completed_selection,
        )

    (
        waiting_for_literature,
        waiting_for_selection,
        completed_selection,
    ) = asyncio.run(run_flow())

    assert waiting_for_literature["__interrupt__"][0].value == {
        "literature_run_id": 7,
        "message": "Waiting for literature search to complete",
    }
    assert waiting_for_literature["literature_message_id"] == "message-7"
    dispatcher.dispatch.assert_awaited_once_with(
        7,
        resume_workflow=True,
    )

    assert waiting_for_selection["__interrupt__"][0].value == {
        "literature_run_id": 7,
        "message": "Please select papers before continuing",
    }

    assert completed_selection["selected_paper_ids"] == [51, 42]
    assert completed_selection["code_requirements"] == "Use PyTorch"
    assert completed_selection["status"] == "completed"
    assert completed_selection["next_step"] == "finish"
    assert [
        report["paper_id"]
        for report in completed_selection["validation_reports"]
    ] == [51, 42]
    assert [
        paper["paper_id"]
        for paper in completed_selection["selected_papers"]
    ] == [51, 42]
    assert [
        artifact["paper_id"]
        for artifact in completed_selection["code_artifacts"]
    ] == [51, 42]
    code_input_loader.load.assert_awaited_once_with(7, [51, 42])
    code_agent.run.assert_awaited_once()
    code_request = code_agent.run.await_args.args[0]
    assert code_request.literature_run_id == 7
    assert [paper.paper_id for paper in code_request.papers] == [51, 42]
    assert code_request.code_requirements == "Use PyTorch"


def test_main_graph_dispatches_code_job_and_pauses_for_worker() -> None:
    code_input_loader = _code_input_loader()
    code_input_loader.load.return_value = [
        CodePaperInput(
            paper_id=51,
            source="openalex",
            source_id="W51",
            title="Paper 51",
        )
    ]
    code_queue = AsyncMock(spec=CodeJobQueue)
    code_queue.enqueue.return_value = "code-message-1"
    graph = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=code_input_loader,
        validation_agent=_validation_agent(),
        code_run_service=AsyncMock(spec=CodeRunService),
        code_job_queue=code_queue,
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "queued-code"}}

    async def run_flow():
        await graph.ainvoke(
            {
                "literature_run_id": 7,
                "trace_id": "7df222d3-c065-462f-8f86-f474ff32aa61",
                "status": "waiting_for_paper_selection",
                "next_step": "paper_selection",
                "compute_target": "gpu",
            },
            config,
        )
        return await graph.ainvoke(
            Command(resume={"selected_paper_ids": [51]}),
            config,
        )

    paused = asyncio.run(run_flow())

    assert paused["status"] == "waiting_for_code"
    assert paused["code_message_id"] == "code-message-1"
    assert paused["__interrupt__"][0].value["literature_run_id"] == 7
    request = code_queue.enqueue.await_args.args[0]
    assert request.papers[0].paper_id == 51
    assert code_queue.enqueue.await_args.kwargs["compute_target"] is ComputeTarget.GPU


def test_literature_wait_node_rejects_another_run_completion() -> None:
    graph = _literature_wait_graph()
    config = {"configurable": {"thread_id": "literature-wait-mismatch"}}
    graph.invoke({"literature_run_id": 7}, config)

    with pytest.raises(ValueError, match="does not match workflow"):
        graph.invoke(
            Command(resume={"literature_run_id": 8}),
            config,
        )


@pytest.mark.parametrize("run_id", [None, 0, -1, True, "7"])
def test_paper_selection_node_rejects_invalid_run_id(run_id: object) -> None:
    workflow = object.__new__(ModuleBuildWorkflow)

    with pytest.raises(ValueError, match="positive integer"):
        workflow._paper_selection_node({"literature_run_id": run_id})  # type: ignore[typeddict-item]


@pytest.mark.parametrize("run_id", [None, 0, -1, True, "7"])
def test_literature_wait_node_rejects_invalid_run_id(run_id: object) -> None:
    workflow = object.__new__(ModuleBuildWorkflow)

    with pytest.raises(ValueError, match="positive integer"):
        workflow._literature_wait_node({"literature_run_id": run_id})  # type: ignore[typeddict-item]


def test_literature_dispatch_records_successful_attempt() -> None:
    dispatcher = _dispatcher()
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )

    result = asyncio.run(
        workflow._literature_dispatch_node({"literature_run_id": 7})
    )

    assert result["literature_message_id"] == "message-7"
    assert result["attempts"] == {"literature": 1}
    assert result["status"] == "searching_literature"


@pytest.mark.parametrize(
    ("existing_attempts", "expected_attempt", "retryable"),
    [({}, 1, True), ({"literature": 1}, 2, False)],
)
def test_literature_dispatch_converts_timeout_to_failure(
    existing_attempts: dict[str, int],
    expected_attempt: int,
    retryable: bool,
) -> None:
    dispatcher = _dispatcher()
    dispatcher.dispatch.side_effect = TimeoutError("Broker timed out")
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )
    state: ModuleGraphState = {
        "literature_run_id": 7,
        "attempts": existing_attempts,
    }

    result = asyncio.run(workflow._literature_dispatch_node(state))
    failure = WorkflowFailure.model_validate(result["failure"])

    assert "literature_message_id" not in result
    assert result["attempts"] == {"literature": expected_attempt}
    assert result["status"] == "failed"
    assert failure.attempt == expected_attempt
    assert failure.retryable is retryable


def test_main_graph_retries_literature_timeout_once() -> None:
    dispatcher = _dispatcher()
    dispatcher.dispatch.side_effect = [
        TimeoutError("Broker timed out"),
        "message-after-retry",
    ]
    graph = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "literature-retry"}}

    result = asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "status": "searching_literature",
                "next_step": "literature",
            },
            config,
        )
    )

    assert dispatcher.dispatch.await_count == 2
    assert result["literature_message_id"] == "message-after-retry"
    assert result["attempts"] == {"literature": 2}
    assert result["failure"] is None
    assert result["__interrupt__"][0].value["literature_run_id"] == 7


def test_main_graph_stops_after_literature_retry_budget_is_exhausted() -> None:
    dispatcher = _dispatcher()
    dispatcher.dispatch.side_effect = TimeoutError("Broker timed out")
    graph = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "literature-retry-stop"}}

    result = asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "status": "searching_literature",
                "next_step": "literature",
            },
            config,
        )
    )
    failure = WorkflowFailure.model_validate(result["failure"])

    assert dispatcher.dispatch.await_count == 2
    assert result["attempts"] == {"literature": 2}
    assert result["status"] == "failed"
    assert result["next_step"] == "finish"
    assert failure.retryable is False
    assert "__interrupt__" not in result


def test_code_node_records_successful_attempt() -> None:
    loader = _code_input_loader()
    loader.load.return_value = [
        CodePaperInput(
            paper_id=51,
            source="openalex",
            source_id="W51",
            title="Paper 51",
        )
    ]
    code_agent = _code_agent()
    code_agent.run.return_value = [
        CodeArtifact(
            paper_id=51,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
            reproduction_plan=ReproductionPlan(
                research_problem="Problem 51",
                implementation_steps=["Implement method"],
            ),
        )
    ]
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=code_agent,
        code_input_loader=loader,
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )

    result = asyncio.run(
        workflow._code_node(
            {
                "literature_run_id": 7,
                "selected_paper_ids": [51],
            }
        )
    )

    assert result["attempts"] == {"code": 1}
    assert result["status"] == "code_ready"
    assert result["code_artifacts"][0]["paper_id"] == 51


def test_code_node_converts_input_loading_error_to_failure() -> None:
    loader = _code_input_loader()
    loader.load.side_effect = ConnectionError("Database unavailable")
    code_agent = _code_agent()
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=code_agent,
        code_input_loader=loader,
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    )

    result = asyncio.run(
        workflow._code_node(
            {
                "literature_run_id": 7,
                "selected_paper_ids": [51],
            }
        )
    )
    failure = WorkflowFailure.model_validate(result["failure"])

    assert result["attempts"] == {"code": 1}
    assert result["status"] == "failed"
    assert failure.step.value == "code"
    assert failure.retryable is False
    code_agent.run.assert_not_awaited()


def test_main_graph_does_not_retry_code_failure() -> None:
    loader = _code_input_loader()
    loader.load.return_value = [
        CodePaperInput(
            paper_id=51,
            source="openalex",
            source_id="W51",
            title="Paper 51",
        )
    ]
    code_agent = _code_agent()
    code_agent.run.side_effect = TimeoutError("Code preparation timed out")
    graph = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=code_agent,
        code_input_loader=loader,
        validation_agent=_validation_agent(),
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "code-no-retry"}}

    result = asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "selected_paper_ids": [51],
                "status": "preparing_code",
                "next_step": "code",
            },
            config,
        )
    )
    failure = WorkflowFailure.model_validate(result["failure"])

    assert code_agent.run.await_count == 1
    assert result["attempts"] == {"code": 1}
    assert result["status"] == "failed"
    assert result["next_step"] == "finish"
    assert failure.retryable is False


def test_validation_business_failure_still_completes_workflow() -> None:
    artifact = _artifact()
    validation_agent = AsyncMock(spec=ValidationAgent)
    validation_agent.run.return_value = [
        _report(artifact, status=ValidationStatus.FAILED)
    ]
    workflow = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=validation_agent,
        checkpointer=InMemorySaver(),
    )

    result = asyncio.run(
        workflow._validation_node(
            {
                "literature_run_id": 7,
                "code_artifacts": [artifact.model_dump(mode="json")],
            }
        )
    )

    assert result["attempts"] == {"validation": 1}
    assert result["status"] == "completed"
    assert result["validation_reports"][0]["status"] == "failed"
    assert "failure" not in result


def test_main_graph_retries_validation_timeout_once() -> None:
    artifact = _artifact()
    validation_agent = AsyncMock(spec=ValidationAgent)
    validation_agent.run.side_effect = [
        TimeoutError("Validation timed out"),
        [_report(artifact)],
    ]
    graph = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=validation_agent,
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "validation-retry"}}

    result = asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "selected_paper_ids": [51],
                "code_artifacts": [artifact.model_dump(mode="json")],
                "status": "validating",
                "next_step": "validation",
            },
            config,
        )
    )

    assert validation_agent.run.await_count == 2
    assert result["attempts"] == {"validation": 2}
    assert result["failure"] is None
    assert result["status"] == "completed"
    assert result["next_step"] == "finish"


def test_main_graph_stops_after_validation_retry_budget_is_exhausted() -> None:
    artifact = _artifact()
    validation_agent = AsyncMock(spec=ValidationAgent)
    validation_agent.run.side_effect = TimeoutError(
        "Validation timed out"
    )
    graph = ModuleBuildWorkflow(
        literature_dispatcher=_dispatcher(),
        code_agent=_code_agent(),
        code_input_loader=_code_input_loader(),
        validation_agent=validation_agent,
        checkpointer=InMemorySaver(),
    ).build()
    config = {"configurable": {"thread_id": "validation-retry-stop"}}

    result = asyncio.run(
        graph.ainvoke(
            {
                "literature_run_id": 7,
                "selected_paper_ids": [51],
                "code_artifacts": [artifact.model_dump(mode="json")],
                "status": "validating",
                "next_step": "validation",
            },
            config,
        )
    )
    failure = WorkflowFailure.model_validate(result["failure"])

    assert validation_agent.run.await_count == 2
    assert result["attempts"] == {"validation": 2}
    assert result["status"] == "failed"
    assert result["next_step"] == "finish"
    assert failure.retryable is False
