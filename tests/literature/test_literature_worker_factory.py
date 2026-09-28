from unittest.mock import ANY, AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.bootstrap import worker_factories
from module_agent.code.application.agent import CodeAgent
from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.supervision.adapters.database.observation_sink import (
    SqlAlchemySupervisorObservationSink,
)
from module_agent.shared.cache.redis import redis_client
from module_agent.bootstrap.worker_factories import (
    build_literature_run_executor,
    build_literature_run_service,
    build_module_workflow_coordinator,
)


def test_worker_factory_reuses_supplied_session_and_shared_cache_client() -> None:
    session = AsyncMock(spec=AsyncSession)

    executor = build_literature_run_executor(session)

    assert executor.run_service.repository.session is session
    assert executor.agent.venue_quality_service.repository.session is session
    assert executor.agent.paper_catalog_service is not None
    assert executor.agent.paper_catalog_service.repository.session is session
    assert executor.agent.venue_quality_service.cache is not None
    assert executor.agent.venue_quality_service.cache._client is redis_client
    assert executor.agent.search_service.sources


def test_run_service_factory_reuses_supplied_session() -> None:
    session = AsyncMock(spec=AsyncSession)

    service = build_literature_run_service(session)

    assert service.repository.session is session


def test_module_workflow_coordinator_factory_reuses_session_and_checkpointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        worker_factories.app_settings,
        "github_token",
        "test-github-token",
    )
    session = AsyncMock(spec=AsyncSession)
    checkpointer = AsyncMock(spec=AsyncPostgresSaver)
    github_client = MagicMock(spec=httpx.AsyncClient)
    get_github_client = MagicMock(return_value=github_client)
    code_agent = MagicMock(spec=CodeAgent)
    build_code_agent = MagicMock(return_value=code_agent)
    supervisor_agent = MagicMock(spec=SupervisorAgent)
    build_supervisor_agent = MagicMock(
        return_value=supervisor_agent
    )
    monkeypatch.setattr(
        worker_factories.github_client_manager,
        "get_client",
        get_github_client,
    )
    monkeypatch.setattr(
        worker_factories,
        "build_code_agent",
        build_code_agent,
    )
    monkeypatch.setattr(
        worker_factories,
        "build_supervisor_agent",
        build_supervisor_agent,
    )

    coordinator = build_module_workflow_coordinator(
        session,
        checkpointer,
    )

    assert coordinator.run_service.repository.session is session
    assert (
        coordinator.selection_service.literature_run_repository.session
        is session
    )
    assert (
        coordinator.selection_service.paper_selection_repository.session
        is session
    )
    assert coordinator.workflow_service.graph.checkpointer is checkpointer
    get_github_client.assert_called_once_with()
    build_code_agent.assert_called_once_with(
        github_client=github_client,
        github_token=worker_factories.app_settings.github_token,
        github_api_version=worker_factories.app_settings.github_api_version,
        qwen_client_manager=worker_factories.qwen_client_manager,
        qwen_model=worker_factories.app_settings.qwen_model,
        workspace_root=worker_factories.app_settings.code_workspace_root,
        git_timeout_seconds=(
            worker_factories.app_settings.git_clone_timeout_seconds
        ),
        confidence_threshold=(
            worker_factories.app_settings.code_repository_confidence_threshold
        ),
            search_limit=(
                worker_factories.app_settings.code_repository_search_limit
            ),
            pdf_max_bytes=(
                worker_factories.app_settings.code_pdf_max_bytes
            ),
            pdf_timeout_seconds=(
                worker_factories.app_settings.code_pdf_timeout_seconds
            ),
            pdf_parse_timeout_seconds=(
                worker_factories.app_settings.code_pdf_parse_timeout_seconds
            ),
            pdf_max_pages=(
                worker_factories.app_settings.code_pdf_max_pages
            ),
            pdf_parse_memory_bytes=(
                worker_factories.app_settings.code_pdf_parse_memory_bytes
            ),
            landing_page_max_bytes=(
                worker_factories.app_settings.code_landing_page_max_bytes
            ),
        )
    build_supervisor_agent.assert_called_once_with(
        mode=worker_factories.app_settings.supervisor_policy,
        typesafe_client_manager=(
            worker_factories.typesafe_client_manager
        ),
        confidence_threshold=(
            worker_factories.app_settings.jev_confidence_threshold
        ),
        observation_sink=ANY,
    )
    observation_sink = (
        build_supervisor_agent.call_args.kwargs["observation_sink"]
    )
    assert isinstance(
        observation_sink,
        SqlAlchemySupervisorObservationSink,
    )
    assert (
        observation_sink.session_factory
        is worker_factories.async_session_factory
    )
