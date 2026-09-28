import asyncio
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

from langgraph.checkpoint.memory import InMemorySaver

from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)
from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.run import CodeRunService
from module_agent.code.domain import (
    CodeArtifact,
    CodeArtifactOrigin,
    CodeArtifactStatus,
    CodePaperInput,
    CodeRun,
    ReproductionPlan,
)
from module_agent.literature.application.dispatch import (
    LiteratureRunDispatcher,
)
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.domain import ValidationRun
from module_agent.workflow.code_input import SelectedPaperCodeInputLoader
from module_agent.workflow.domain import PaperSelectionRequest, WorkflowStatus
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.workflow.lifecycle import ModuleWorkflowRun
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.workflow.observation import WorkflowNodeExecution
from module_agent.workflow.service import ModuleWorkflowService


class MemoryCodeRuns:
    def __init__(self) -> None:
        self.runs: list[CodeRun] = []

    async def get_by_id(self, run_id: int) -> CodeRun | None:
        return next((run for run in self.runs if run.id == run_id), None)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> CodeRun | None:
        return next(
            (
                run
                for run in self.runs
                if run.literature_run_id == literature_run_id
                and run.attempt == attempt
            ),
            None,
        )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[CodeRun]:
        return [
            run
            for run in self.runs
            if run.literature_run_id == literature_run_id
        ]

    async def save(self, run: CodeRun) -> CodeRun:
        saved = run.model_copy(
            update={
                "id": run.id or len(self.runs) + 1,
                "created_at": run.created_at or datetime.now(timezone.utc),
            }
        )
        self.runs = [item for item in self.runs if item.id != saved.id]
        self.runs.append(saved)
        return saved


class MemoryValidationRuns:
    def __init__(self) -> None:
        self.runs: list[ValidationRun] = []

    async def get_by_id(self, run_id: int) -> ValidationRun | None:
        return next((run for run in self.runs if run.id == run_id), None)

    async def get_by_execution(
        self,
        literature_run_id: int,
        attempt: int,
    ) -> ValidationRun | None:
        return next(
            (
                run
                for run in self.runs
                if run.literature_run_id == literature_run_id
                and run.attempt == attempt
            ),
            None,
        )

    async def list_by_literature_run(
        self,
        literature_run_id: int,
    ) -> list[ValidationRun]:
        return [
            run
            for run in self.runs
            if run.literature_run_id == literature_run_id
        ]

    async def save(self, run: ValidationRun) -> ValidationRun:
        saved = run.model_copy(
            update={
                "id": run.id or len(self.runs) + 1,
                "created_at": run.created_at or datetime.now(timezone.utc),
            }
        )
        self.runs = [item for item in self.runs if item.id != saved.id]
        self.runs.append(saved)
        return saved


class MemoryWorkflowRuns:
    def __init__(self) -> None:
        self.run: ModuleWorkflowRun | None = None

    async def get(self, _: int) -> ModuleWorkflowRun | None:
        return self.run

    async def save(self, run: ModuleWorkflowRun) -> ModuleWorkflowRun:
        self.run = run
        return run


class MemoryNodeExecutions:
    def __init__(self) -> None:
        self.executions: list[WorkflowNodeExecution] = []

    async def record(
        self,
        execution: WorkflowNodeExecution,
    ) -> WorkflowNodeExecution:
        saved = execution.model_copy(
            update={"id": len(self.executions) + 1}
        )
        self.executions.append(saved)
        return saved


def test_m8_workflow_persists_runs_trace_and_node_observations() -> None:
    code_agent = AsyncMock(spec=CodeAgent)
    code_agent.run.return_value = [
        CodeArtifact(
            paper_id=51,
            origin=CodeArtifactOrigin.REPRODUCTION_PLAN,
            status=CodeArtifactStatus.REPRODUCTION_PLANNED,
            reproduction_plan=ReproductionPlan(
                research_problem="Reproduce paper 51",
                implementation_steps=["Implement the core method"],
            ),
        )
    ]
    loader = AsyncMock(spec=SelectedPaperCodeInputLoader)
    loader.load.return_value = [
        CodePaperInput(
            paper_id=51,
            source="openalex",
            source_id="W51",
            title="Paper 51",
        )
    ]
    validation_agent = build_validation_agent(workspace_root=Path.cwd())
    code_runs = MemoryCodeRuns()
    validation_runs = MemoryValidationRuns()
    workflow_runs = MemoryWorkflowRuns()
    node_executions = MemoryNodeExecutions()
    lifecycle = ModuleWorkflowLifecycleService(
        workflow_runs,
        default_timeout_seconds=300,
    )
    graph = ModuleBuildWorkflow(
        literature_dispatcher=AsyncMock(spec=LiteratureRunDispatcher),
        code_agent=code_agent,
        validation_agent=validation_agent,
        code_input_loader=loader,
        code_run_service=CodeRunService(code_agent, code_runs),
        validation_run_service=ValidationRunService(
            validation_agent,
            validation_runs,
        ),
        lifecycle_service=lifecycle,
        node_execution_recorder=node_executions,
        checkpointer=InMemorySaver(),
    ).build()
    service = ModuleWorkflowService(graph, lifecycle)

    async def execute():
        prompt = await service.start_paper_selection(7)
        state = await service.resume_paper_selection(
            7,
            PaperSelectionRequest(selected_paper_ids=[51]),
        )
        result = await service.get_result(7)
        return prompt, state, result

    prompt, state, result = asyncio.run(execute())

    assert prompt.literature_run_id == 7
    assert state["status"] == WorkflowStatus.COMPLETED.value
    assert result.status is WorkflowStatus.COMPLETED
    assert workflow_runs.run is not None
    assert workflow_runs.run.status.value == "completed"
    assert len(code_runs.runs) == 1
    assert len(validation_runs.runs) == 1
    assert code_runs.runs[0].trace_id == workflow_runs.run.trace_id
    assert validation_runs.runs[0].trace_id == workflow_runs.run.trace_id
    assert {execution.node for execution in node_executions.executions} >= {
        "paper_selection",
        "code",
        "validation",
        "supervisor",
    }
