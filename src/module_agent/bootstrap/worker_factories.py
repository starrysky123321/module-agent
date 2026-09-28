from sqlalchemy.ext.asyncio import AsyncSession
from module_agent.literature.application.execution import LiteratureRunExecutor
from module_agent.literature.adapters.sources.registry import LITERATURE_SOURCE_REGISTRY
from module_agent.literature.application.search import LiteratureSearchService
from module_agent.literature.application.run import LiteratureRunService
from module_agent.literature.application.agent import LiteratureAgent
from module_agent.literature.adapters.database.repositories.paper import (
    SqlAlchemyPaperRepository,
)
from module_agent.literature.adapters.database.repositories.code_status import (
    SqlAlchemyPaperCodeStatusWriter,
)
from module_agent.literature.adapters.database.repositories.run import (
    SqlAlchemyLiteratureRunRepository,
)
from module_agent.venue_catalog.adapters.database.repository import (
    SqlAlchemyVenueRepository,
)
from module_agent.venue_catalog.adapters.cache import RedisVenueCache
from module_agent.venue_catalog.application.quality import VenueQualityService
from module_agent.literature.application.catalog import PaperCatalogService
from module_agent.shared.config import app_settings
from module_agent.shared.cache.redis import redis_client
from module_agent.literature.domain.source import LiteratureSource
from module_agent.bootstrap.factories.query_planner import build_literature_query_planner
from module_agent.shared.llm.qwen_client import qwen_client_manager
from module_agent.bootstrap.factories.relevance_scorer import build_paper_relevance_scorer
from module_agent.bootstrap.factories.method_extractor import build_paper_method_extractor
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from module_agent.code.application.agent import CodeAgent
from module_agent.code.application.run import CodeRunService
from module_agent.code.adapters.database.repositories.run import (
    TransactionalCodeRunRepository,
)
from module_agent.validation.application.run import ValidationRunService
from module_agent.validation.adapters.database.repositories.run import (
    TransactionalValidationRunRepository,
)
from module_agent.supervision.application.agent import SupervisorAgent
from module_agent.literature.adapters.database.repositories.selection import (
    SqlAlchemyPaperSelectionRepository,
)
from module_agent.shared.messaging.rabbitmq import (
    rabbitmq_connection_manager,
)
from module_agent.literature.adapters.messaging.job_queue import (
    RabbitMQLiteratureJobQueue,
)
from module_agent.literature.application.dispatch import LiteratureRunDispatcher
from module_agent.workflow.service import ModuleWorkflowService
from module_agent.workflow.coordinator import (
    ModuleWorkflowCoordinator,
)
from module_agent.literature.application.selection import PaperSelectionService
from module_agent.workflow.graph import ModuleBuildWorkflow
from module_agent.bootstrap.factories.code_agent import build_code_agent
from module_agent.bootstrap.factories.validation_agent import (
    build_validation_agent,
)
from module_agent.code.adapters.github_client import github_client_manager
from module_agent.workflow.code_input import (
    SelectedPaperCodeInputLoader,
)
from module_agent.bootstrap.factories.supervisor_agent import (
    build_supervisor_agent,
)
from module_agent.shared.decision.typesafe_client import (
    typesafe_client_manager,
)
from module_agent.shared.database.session import async_session_factory
from module_agent.supervision.adapters.database.observation_sink import (
    SqlAlchemySupervisorObservationSink,
)
from module_agent.workflow.adapters.database.repository import (
    TransactionalModuleWorkflowRunRepository,
)
from module_agent.workflow.lifecycle_service import (
    ModuleWorkflowLifecycleService,
)
from module_agent.workflow.adapters.database.node_execution import (
    SqlAlchemyWorkflowNodeExecutionRepository,
)
from module_agent.code.adapters.messaging.job_queue import RabbitMQCodeJobQueue



def build_literature_run_executor(
    session: AsyncSession,
) -> LiteratureRunExecutor:
    """构建并返回目标对象。"""
    sources: list[LiteratureSource] = [
        LITERATURE_SOURCE_REGISTRY[name]
        for name in app_settings.literature_sources
    ]
    search_service = LiteratureSearchService(sources)
    query_planner = build_literature_query_planner(
        mode=app_settings.literature_query_planner,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )
    venue_repository = SqlAlchemyVenueRepository(session)
    venue_cache = RedisVenueCache(redis_client)
    venue_quality_service = VenueQualityService(
        venue_repository,
        venue_cache,
    )

    paper_repository = SqlAlchemyPaperRepository(session)
    paper_catalog_service = PaperCatalogService(paper_repository)
    relevance_scorer = build_paper_relevance_scorer(
        mode=app_settings.literature_relevance_scorer,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )
    method_extractor = build_paper_method_extractor(
        mode=app_settings.literature_method_extractor,
        qwen_model=app_settings.qwen_model,
        qwen_client_manager=qwen_client_manager,
        timeout_seconds=app_settings.qwen_call_timeout_seconds,
    )

    agent = LiteratureAgent(
        search_service=search_service,
        venue_quality_service=venue_quality_service,
        query_planner=query_planner,
        relevance_scorer=relevance_scorer,
        paper_catalog_service=paper_catalog_service,
        method_extractor=method_extractor,
    )

    run_service = build_literature_run_service(session)

    return LiteratureRunExecutor(agent, run_service)



def build_literature_run_service(session: AsyncSession) -> LiteratureRunService:
    """构建并返回目标对象。"""
    run_repository = SqlAlchemyLiteratureRunRepository(session)
    run_service = LiteratureRunService(run_repository)
    
    return run_service


def build_code_run_service() -> CodeRunService:
    """Build the durable Code Agent application service for a worker."""
    code_agent = build_code_agent(
        github_client=github_client_manager.get_client(),
        github_token=app_settings.github_token,
        github_api_version=app_settings.github_api_version,
        qwen_client_manager=qwen_client_manager,
        qwen_model=app_settings.qwen_model,
        workspace_root=app_settings.code_workspace_root,
        git_timeout_seconds=app_settings.git_clone_timeout_seconds,
        confidence_threshold=(
            app_settings.code_repository_confidence_threshold
        ),
        search_limit=app_settings.code_repository_search_limit,
        pdf_max_bytes=app_settings.code_pdf_max_bytes,
        pdf_timeout_seconds=app_settings.code_pdf_timeout_seconds,
        landing_page_max_bytes=app_settings.code_landing_page_max_bytes,
    )
    return CodeRunService(
        code_agent,
        TransactionalCodeRunRepository(async_session_factory),
        SqlAlchemyPaperCodeStatusWriter(async_session_factory),
    )


def build_module_workflow_coordinator(
    session: AsyncSession,
    checkpointer: AsyncPostgresSaver,
) -> ModuleWorkflowCoordinator:
    """构建并返回目标对象。"""
    run_service = build_literature_run_service(session)
    selection_service = PaperSelectionService(
        literature_run_repository=run_service.repository,
        paper_selection_repository=SqlAlchemyPaperSelectionRepository(
            session
        ),
    )
    dispatcher = LiteratureRunDispatcher(
        run_service=run_service,
        job_queue=RabbitMQLiteratureJobQueue(
            rabbitmq_connection_manager
        ),
    )
    code_agent = build_code_agent(
        github_client=github_client_manager.get_client(),
        github_token=app_settings.github_token,
        github_api_version=app_settings.github_api_version,
        qwen_client_manager=qwen_client_manager,
        qwen_model=app_settings.qwen_model,
        workspace_root=app_settings.code_workspace_root,
        git_timeout_seconds=app_settings.git_clone_timeout_seconds,
        confidence_threshold=(
            app_settings.code_repository_confidence_threshold
        ),
        search_limit=app_settings.code_repository_search_limit,
        pdf_max_bytes=app_settings.code_pdf_max_bytes,
        pdf_timeout_seconds=app_settings.code_pdf_timeout_seconds,
        landing_page_max_bytes=app_settings.code_landing_page_max_bytes,
    )
    validation_agent = build_validation_agent(
        workspace_root=app_settings.code_workspace_root,
        sandbox_image=app_settings.validation_sandbox_image,
        git_timeout_seconds=(
            app_settings.validation_git_timeout_seconds
        ),
    )
    lifecycle_service = ModuleWorkflowLifecycleService(
        TransactionalModuleWorkflowRunRepository(async_session_factory),
        default_timeout_seconds=app_settings.workflow_timeout_seconds,
    )
    graph = ModuleBuildWorkflow(
        literature_dispatcher=dispatcher,
        code_agent=code_agent,
        code_input_loader=SelectedPaperCodeInputLoader(
            paper_repository=SqlAlchemyPaperRepository(session),
            literature_run_repository=run_service.repository,
        ),
        validation_agent=validation_agent,
        code_run_service=CodeRunService(
            code_agent,
            TransactionalCodeRunRepository(async_session_factory),
            SqlAlchemyPaperCodeStatusWriter(async_session_factory),
        ),
        validation_run_service=ValidationRunService(
            validation_agent,
            TransactionalValidationRunRepository(
                async_session_factory
            ),
        ),
        lifecycle_service=lifecycle_service,
        node_execution_recorder=(
            SqlAlchemyWorkflowNodeExecutionRepository(
                async_session_factory
            )
        ),
        code_job_queue=RabbitMQCodeJobQueue(
            rabbitmq_connection_manager
        ),
        supervisor_agent=build_supervisor_agent(
            mode=app_settings.supervisor_policy,
            typesafe_client_manager=typesafe_client_manager,
            confidence_threshold=(
                app_settings.jev_confidence_threshold
            ),
            observation_sink=SqlAlchemySupervisorObservationSink(
                async_session_factory
            ),
        ),
        checkpointer=checkpointer,
    ).build()
    workflow_service = ModuleWorkflowService(graph, lifecycle_service)

    return ModuleWorkflowCoordinator(
        workflow_service=workflow_service,
        run_service=run_service,
        selection_service=selection_service,
    )
