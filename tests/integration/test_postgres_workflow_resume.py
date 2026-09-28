import asyncio
import os
from pathlib import Path
from uuid import uuid4
from unittest.mock import AsyncMock, MagicMock

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.shared.config import app_settings
from module_agent.workflow.domain import PaperSelectionRequest
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
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


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_DATABASE_INTEGRATION_TESTS") != "1",
    reason="set RUN_DATABASE_INTEGRATION_TESTS=1 to test PostgreSQL resume",
)


def _workflow_service(checkpointer: AsyncPostgresSaver) -> ModuleWorkflowService:
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
        checkpointer=checkpointer,
    ).build()
    return ModuleWorkflowService(graph)


def test_workflow_resumes_after_postgres_connection_is_reopened() -> None:
    database_url = app_settings.langgraph_database_url
    assert database_url, "LANGGRAPH_DATABASE_URL must be configured"

    run_id = uuid4().int % 2_000_000_000 + 1
    thread_id = f"literature-run:{run_id}"

    async def verify() -> None:
        try:
            async with AsyncPostgresSaver.from_conn_string(
                database_url
            ) as first_checkpointer:
                first_service = _workflow_service(first_checkpointer)
                prompt = await first_service.start_paper_selection(
                    run_id,
                    code_requirements="Use PyTorch",
                )

                assert prompt.literature_run_id == run_id

            async with AsyncPostgresSaver.from_conn_string(
                database_url
            ) as second_checkpointer:
                second_service = _workflow_service(second_checkpointer)
                restored_prompt = await second_service.start_paper_selection(
                    run_id
                )
                state = await second_service.resume_paper_selection(
                    run_id,
                    PaperSelectionRequest(selected_paper_ids=[51, 42]),
                )

                assert restored_prompt == prompt
                assert state["selected_paper_ids"] == [51, 42]
                assert state["code_requirements"] == "Use PyTorch"
                assert state["status"] == "completed"
                assert state["next_step"] == "finish"
        finally:
            async with AsyncPostgresSaver.from_conn_string(
                database_url
            ) as cleanup_checkpointer:
                await cleanup_checkpointer.adelete_thread(thread_id)

    asyncio.run(verify())
