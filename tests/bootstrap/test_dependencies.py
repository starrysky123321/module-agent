import asyncio
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from module_agent.literature.application.agent import LiteratureAgent
from module_agent.code.application.agent import CodeAgent
from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.supervision.domain import SupervisorObservationSink
from module_agent.validation.application.agent import ValidationAgent
from module_agent.bootstrap.api_dependencies import (
    get_code_agent,
    get_module_build_graph,
    get_module_workflow_service,
    get_module_workflow_coordinator,
    get_supervisor_agent,
    get_supervisor_observation_sink,
    get_validation_agent,
    get_literature_agent,
    get_paper_relevance_scorer,
    get_literature_query_planner,
    get_literature_run_dispatcher,
    get_literature_run_executor,
    get_literature_run_service,
    get_langgraph_checkpointer,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from module_agent.shared.checkpoint.postgres import (
    postgres_checkpointer_manager,
)
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)
from module_agent.venue_catalog.adapters.database.repository import (
    SqlAlchemyVenueRepository,
)
from module_agent.literature.adapters.database.repositories.paper import (
    SqlAlchemyPaperRepository,
)
from module_agent.venue_catalog.adapters.cache import RedisVenueCache
from module_agent.shared.database.session import get_database_session
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.literature.application.query_planning import (
    RuleBasedLiteratureQueryPlanner,
)
from module_agent.literature.application.relevance import (
    RuleBasedPaperRelevanceScorer,
)
from module_agent.literature.adapters.messaging.job_queue import (
    RabbitMQLiteratureJobQueue,
)
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.literature.application.selection import PaperSelectionService
from module_agent.bootstrap import api_dependencies
from module_agent.supervision.adapters.database.observation_sink import (
    SqlAlchemySupervisorObservationSink,
)


def test_fastapi_builds_literature_agent_dependency_chain() -> None:
    application = FastAPI()
    session = AsyncMock(spec=AsyncSession)

    async def override_database_session():
        yield session

    application.dependency_overrides[get_database_session] = (
        override_database_session
    )
    application.dependency_overrides[get_literature_query_planner] = (
        RuleBasedLiteratureQueryPlanner
    )
    application.dependency_overrides[get_paper_relevance_scorer] = (
        RuleBasedPaperRelevanceScorer
    )

    @application.get("/dependency-check")
    async def dependency_check(
        agent: Annotated[LiteratureAgent, Depends(get_literature_agent)],
        run_service: Annotated[
            LiteratureRunService,
            Depends(get_literature_run_service),
        ],
        executor: Annotated[
            LiteratureRunExecutor,
            Depends(get_literature_run_executor),
        ],
        dispatcher: Annotated[
            LiteratureRunDispatcher,
            Depends(get_literature_run_dispatcher),
        ],
    ) -> dict[str, bool]:
        repository = agent.venue_quality_service.repository
        paper_repository = agent.paper_catalog_service.repository
        return {
            "is_repository": isinstance(repository, SqlAlchemyVenueRepository),
            "uses_request_session": repository.session is session,
            "is_venue_cache": isinstance(
                agent.venue_quality_service.cache,
                RedisVenueCache,
            ),
            "is_paper_repository": isinstance(
                paper_repository,
                SqlAlchemyPaperRepository,
            ),
            "is_query_planner": isinstance(
                agent.query_planner,
                RuleBasedLiteratureQueryPlanner,
            ),
            "is_relevance_scorer": isinstance(
                agent.relevance_scorer,
                RuleBasedPaperRelevanceScorer,
            ),
            "paper_uses_request_session": paper_repository.session is session,
            "is_run_repository": isinstance(
                run_service.repository,
                SqlAlchemyLiteratureRunRepository,
            ),
            "run_uses_request_session": run_service.repository.session is session,
            "executor_uses_agent": executor.agent is agent,
            "executor_uses_run_service": executor.run_service is run_service,
            "dispatcher_uses_run_service": dispatcher.run_service is run_service,
            "dispatcher_uses_rabbitmq": isinstance(
                dispatcher.job_queue,
                RabbitMQLiteratureJobQueue,
            ),
        }

    async def request_dependency_check() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/dependency-check")

    response = asyncio.run(request_dependency_check())

    assert response.status_code == 200
    assert response.json() == {
        "is_repository": True,
        "uses_request_session": True,
        "is_venue_cache": True,
        "is_paper_repository": True,
        "is_query_planner": True,
        "is_relevance_scorer": True,
        "paper_uses_request_session": True,
        "is_run_repository": True,
        "run_uses_request_session": True,
        "executor_uses_agent": True,
        "executor_uses_run_service": True,
        "dispatcher_uses_run_service": True,
        "dispatcher_uses_rabbitmq": True,
    }


def test_langgraph_checkpointer_dependency_returns_started_saver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    saver = object()
    get_checkpointer = MagicMock(return_value=saver)
    monkeypatch.setattr(
        postgres_checkpointer_manager,
        "get_checkpointer",
        get_checkpointer,
    )

    assert get_langgraph_checkpointer() is saver
    get_checkpointer.assert_called_once_with()


def test_langgraph_checkpointer_dependency_does_not_start_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_checkpointer = MagicMock(
        side_effect=RuntimeError("manager is not started")
    )
    start = AsyncMock()
    monkeypatch.setattr(
        postgres_checkpointer_manager,
        "get_checkpointer",
        get_checkpointer,
    )
    monkeypatch.setattr(postgres_checkpointer_manager, "start", start)

    with pytest.raises(RuntimeError, match="not started"):
        get_langgraph_checkpointer()

    start.assert_not_awaited()


def test_code_agent_dependency_uses_shared_clients_and_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_dependencies.app_settings,
        "github_token",
        "test-github-token",
    )
    github_client = MagicMock(spec=httpx.AsyncClient)
    get_github_client = MagicMock(return_value=github_client)
    code_agent = MagicMock(spec=CodeAgent)
    factory = MagicMock(return_value=code_agent)
    monkeypatch.setattr(
        api_dependencies.github_client_manager,
        "get_client",
        get_github_client,
    )
    monkeypatch.setattr(api_dependencies, "build_code_agent", factory)

    result = get_code_agent()

    assert result is code_agent
    get_github_client.assert_called_once_with()
    factory.assert_called_once_with(
        github_client=github_client,
        github_token=api_dependencies.app_settings.github_token,
        github_api_version=(
            api_dependencies.app_settings.github_api_version
        ),
        qwen_client_manager=api_dependencies.qwen_client_manager,
        qwen_model=api_dependencies.app_settings.qwen_model,
        workspace_root=(
            api_dependencies.app_settings.code_workspace_root
        ),
        git_timeout_seconds=(
            api_dependencies.app_settings.git_clone_timeout_seconds
        ),
        confidence_threshold=(
            api_dependencies.app_settings.code_repository_confidence_threshold
        ),
            search_limit=(
                api_dependencies.app_settings.code_repository_search_limit
            ),
            pdf_max_bytes=(
                api_dependencies.app_settings.code_pdf_max_bytes
            ),
            pdf_timeout_seconds=(
                api_dependencies.app_settings.code_pdf_timeout_seconds
            ),
            landing_page_max_bytes=(
                api_dependencies.app_settings.code_landing_page_max_bytes
            ),
        )


def test_supervisor_agent_dependency_uses_shared_factory_and_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor_agent = MagicMock(spec=SupervisorAgent)
    observation_sink = MagicMock(spec=SupervisorObservationSink)
    factory = MagicMock(return_value=supervisor_agent)
    monkeypatch.setattr(
        api_dependencies,
        "build_supervisor_agent",
        factory,
    )

    result = get_supervisor_agent(observation_sink)

    assert result is supervisor_agent
    factory.assert_called_once_with(
        mode=api_dependencies.app_settings.supervisor_policy,
        typesafe_client_manager=(
            api_dependencies.typesafe_client_manager
        ),
        confidence_threshold=(
            api_dependencies.app_settings.jev_confidence_threshold
        ),
        observation_sink=observation_sink,
    )


def test_supervisor_observation_sink_uses_independent_session_factory() -> None:
    sink = get_supervisor_observation_sink()

    assert isinstance(sink, SqlAlchemySupervisorObservationSink)
    assert sink.session_factory is api_dependencies.async_session_factory


def test_fastapi_builds_module_workflow_with_injected_dependencies() -> None:
    application = FastAPI()
    literature_dispatcher = MagicMock(spec=LiteratureRunDispatcher)
    code_agent = MagicMock(spec=CodeAgent)
    validation_agent = MagicMock(spec=ValidationAgent)
    supervisor_agent = SupervisorAgent()
    checkpointer = InMemorySaver()
    application.dependency_overrides[get_literature_run_dispatcher] = (
        lambda: literature_dispatcher
    )
    application.dependency_overrides[get_code_agent] = lambda: code_agent
    application.dependency_overrides[get_validation_agent] = (
        lambda: validation_agent
    )
    application.dependency_overrides[get_supervisor_agent] = (
        lambda: supervisor_agent
    )
    application.dependency_overrides[get_langgraph_checkpointer] = (
        lambda: checkpointer
    )

    @application.get("/workflow-dependency-check")
    async def dependency_check(
        graph: Annotated[
            CompiledStateGraph,
            Depends(get_module_build_graph),
        ],
    ) -> dict[str, bool]:
        return {
            "is_compiled_graph": isinstance(graph, CompiledStateGraph),
            "has_literature_dispatch_node": (
                "literature_dispatch" in graph.nodes
            ),
            "has_literature_wait_node": "literature_wait" in graph.nodes,
            "has_selection_node": "paper_selection" in graph.nodes,
            "uses_checkpointer": graph.checkpointer is checkpointer,
        }

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get("/workflow-dependency-check")

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {
        "is_compiled_graph": True,
        "has_literature_dispatch_node": True,
        "has_literature_wait_node": True,
        "has_selection_node": True,
        "uses_checkpointer": True,
    }


def test_module_workflow_service_wraps_injected_graph() -> None:
    graph = MagicMock(spec=CompiledStateGraph)
    lifecycle_service = MagicMock(spec=ModuleWorkflowLifecycleService)

    service = get_module_workflow_service(graph, lifecycle_service)

    assert isinstance(service, ModuleWorkflowService)
    assert service.graph is graph
    assert service.lifecycle_service is lifecycle_service


def test_module_workflow_coordinator_reuses_injected_services() -> None:
    run_service = MagicMock(spec=LiteratureRunService)
    workflow_service = MagicMock(spec=ModuleWorkflowService)
    selection_service = MagicMock(spec=PaperSelectionService)

    coordinator = get_module_workflow_coordinator(
        run_service=run_service,
        workflow_service=workflow_service,
        selection_service=selection_service,
    )

    assert isinstance(coordinator, ModuleWorkflowCoordinator)
    assert coordinator.run_service is run_service
    assert coordinator.workflow_service is workflow_service
    assert coordinator.selection_service is selection_service
